"""
Machine-local files for one ZEISS microscope.
=============================================
Two things about a microscope should survive closing and reopening ZMART:
the frame origin an operator sets with ``set_origin``, and the stage limits
the driver refuses to move beyond. Both live as small JSON files in a
machine-wide folder::

    C:\\ProgramData\\zmart-microscopy\\zeiss\\<microscope_id>\\origin.json
    C:\\ProgramData\\zmart-microscopy\\zeiss\\<microscope_id>\\stage_limits.json

The root can be moved with the ``ZMART_MICROSCOPY_ROOT`` environment variable
or a ``machine_root`` key in the connection dict (tests use a temp folder).
No admin rights are needed: ordinary users can write under ProgramData
subfolders they create.

The ZEN API does not tell us how far the stage can travel, so the limits
file must come from you: the first connect copies the repository defaults
(``limits/defaults/stage_limits.json``) into place and warns, and you replace
those numbers with the real travel range of your stage.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

DEFAULT_PROGRAMDATA_ROOT = Path(r"C:\ProgramData\zmart-microscopy")
VENDOR_DIR = "zeiss"
ORIGIN_FILENAME = "origin.json"
LIMITS_FILENAME = "stage_limits.json"
DEFAULT_LIMITS = Path(__file__).resolve().parent.parent / "limits" / "defaults" / LIMITS_FILENAME


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

    # --- origin ---------------------------------------------------------------

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

    # --- stage limits ---------------------------------------------------------

    def limits_path(self) -> Path:
        return self.machine_dir() / LIMITS_FILENAME

    def ensure_limits_file(self) -> tuple[Path, bool]:
        """Make sure a limits file exists; copy the repository defaults when it does not.

        Returns ``(path, copied_defaults)``. A ``True`` second value means the
        limits in force are the generic defaults, not measured values for
        this stage -- the caller warns the operator.
        """
        path = self.limits_path()
        if path.exists():
            return path, False
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEFAULT_LIMITS, path)
        return path, True

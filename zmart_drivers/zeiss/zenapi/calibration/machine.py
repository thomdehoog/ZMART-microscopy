"""
Machine-local files for one ZEISS microscope.
=============================================
Two things about a microscope should survive closing and reopening ZMART, and
should never mean editing the checkout: the **stage envelope** (how far the
stage may travel, in micrometres) and the **frame origin** an operator sets
with ``set_origin``. Both are small JSON files in a machine-wide folder::

    C:\\ProgramData\\zmart-microscopy\\zeiss\\<microscope_id>\\
        stage_limits.json    # {"stage_um": {"x": [min, max], "y": [...], "z": [...]}}
        origin.json          # the frame zero point, written by set_origin

The stage envelope resolves machine copy first, then the driver-bundled default
under ``limits/defaults/`` -- so the driver ships with a working (generous)
envelope and a machine-specific one never requires touching the repository.
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
PROGRAMDATA_ROOT_ENV = "ZMART_MICROSCOPY_ROOT"
VENDOR_DIR = "zeiss"
STAGE_LIMITS_FILENAME = "stage_limits.json"
ORIGIN_FILENAME = "origin.json"


def bundled_default(filename: str) -> Path:
    """The driver-bundled default for *filename* (``limits/defaults/``)."""
    return Path(__file__).resolve().parents[1] / "limits" / "defaults" / filename


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
        env = os.environ.get(PROGRAMDATA_ROOT_ENV)
        return Path(env) if env else DEFAULT_PROGRAMDATA_ROOT

    def machine_dir(self) -> Path:
        return self.root() / VENDOR_DIR / self.microscope_id

    def resolve(self, filename: str) -> tuple[Path, bool]:
        """Resolve *filename* to ``(path, is_fallback)``: the machine copy, else the bundled default."""
        candidate = self.machine_dir() / filename
        if candidate.exists():
            return candidate, False
        return bundled_default(filename), True

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

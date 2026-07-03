"""Machine-local config for a mesoSPIM: ProgramData copies win, bundled defaults fall back.

Machine state -- the physical stage envelope, the function-keyed safety limits,
and the operator-set frame origin -- lives in a machine-wide ProgramData dir,
one folder per instrument::

    <programdata_root>/mesospim/<microscope_id>/
        stage_limits.json      # physical stage envelope (schema v1)
        function_limits.json   # function-keyed safety limits (shared.limits, v1)
        origin.json            # frame zero point (set_origin; updated in place)

Each file resolves machine copy first, then the driver-bundled default in
``config/`` -- so the defaults ship with the driver and a machine-specific
envelope never requires editing the checkout (the same model as the Leica
sibling). Unlike Leica there are no dated snapshots: mesoSPIM has no
calibration-adopt workflow to write history, so the machine dir holds the
current copy of each file, edited or written in place. If a snapshot-producing
workflow ever lands, this profile is the seam to grow it behind.

``<programdata_root>`` defaults to ``C:\\ProgramData\\smart_microscopy`` and can
be overridden with the ``SMART_MICROSCOPY_ROOT`` env var, or per session with
``connection["machine_root"]`` (which is also how tests stay hermetic).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PROGRAMDATA_ROOT = Path(r"C:\ProgramData\smart_microscopy")
PROGRAMDATA_ROOT_ENV = "SMART_MICROSCOPY_ROOT"

STAGE_LIMITS_FILENAME = "stage_limits.json"
FUNCTION_LIMITS_FILENAME = "function_limits.json"
ORIGIN_FILENAME = "origin.json"


def _bundled_default(filename: str) -> Path:
    """Driver-bundled last-known-good default for *filename* (this config dir)."""
    return Path(__file__).resolve().parent / filename


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(tmp), str(path))


@dataclass(frozen=True)
class MachineProfile:
    """Where this mesoSPIM's machine-local config lives on disk.

    ``programdata_root=None`` resolves to the ``SMART_MICROSCOPY_ROOT`` env var
    if set, else :data:`DEFAULT_PROGRAMDATA_ROOT`. Tests (and the controller's
    ``connection["machine_root"]``) inject an explicit root to stay hermetic.
    """

    microscope_id: str = "mesospim-01"
    programdata_root: Path | None = None

    def root(self) -> Path:
        if self.programdata_root is not None:
            return Path(self.programdata_root)
        env = os.environ.get(PROGRAMDATA_ROOT_ENV)
        return Path(env) if env else DEFAULT_PROGRAMDATA_ROOT

    def machine_dir(self) -> Path:
        return self.root() / "mesospim" / self.microscope_id

    def resolve(self, filename: str) -> tuple[Path, bool]:
        """Resolve *filename* to ``(path, is_fallback)``.

        Prefer the machine copy; fall back to the bundled default when the
        machine dir has no copy of that file.
        """
        candidate = self.machine_dir() / filename
        if candidate.exists():
            return candidate, False
        return _bundled_default(filename), True

    # --- origin: the operator-set frame zero point -----------------------

    def read_origin(self) -> dict | None:
        """The persisted frame origin, or None (never set on this machine)."""
        path = self.machine_dir() / ORIGIN_FILENAME
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_origin(self, payload: dict) -> Path:
        """Persist the frame origin (atomic; creates the machine dir)."""
        path = self.machine_dir() / ORIGIN_FILENAME
        _atomic_write_json(path, payload)
        return path

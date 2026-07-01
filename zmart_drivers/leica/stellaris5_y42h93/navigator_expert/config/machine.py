"""Machine-local resolution of this microscope's coordinate-system config.

Runtime coordinate config - the optical calibration and the physical stage
envelope - lives in dated snapshots under a machine-wide ProgramData root,
newest wins::

    <programdata_root>/<vendor>/<microscope_id>/<datetime>/
        calibration.json    # optical calibration + backlash (schema v11)
        limits.json         # physical stage envelope (schema v1)
        <executed>.ipynb    # the calibration notebook that produced this adopt

Each snapshot is a complete, cumulative machine-state record; the calibration
workflow writes one per adopt by copying the latest snapshot (or the bundled
default) forward and merging its delta.

When no snapshot exists (fresh machine, or a wiped ProgramData tree) the driver
falls back - loudly - to the defaults bundled in the driver at
``defaults/calibration.json`` and ``defaults/limits.json``. Those are a real
last-known-good calibration for this microscope, never an identity/zero
placeholder, so the driver stays usable while warning that a re-calibration is
due.

``<datetime>`` is UTC with microsecond precision, formatted so it is both a
legal Windows path segment (no colons) and lexicographically == chronologically
sortable::

    2026-07-01T14-30-00-123456Z

The active snapshot is the lexical max; a new snapshot must stamp strictly later
than the current latest (:meth:`MachineProfile.new_snapshot_dir`), so a backward
system clock or a same-microsecond re-run can never make a fresh calibration
look stale.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PROGRAMDATA_ROOT = Path(r"C:\ProgramData\smart_microscopy")
PROGRAMDATA_ROOT_ENV = "SMART_MICROSCOPY_ROOT"

# UTC, microsecond precision, Windows-path-safe, lexical order == chronological.
_SNAPSHOT_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"
_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{6}Z$")

CALIBRATION_FILENAME = "calibration.json"
LIMITS_FILENAME = "limits.json"


def _driver_root() -> Path:
    return Path(__file__).resolve().parents[1]  # navigator_expert/


def format_snapshot_name(moment: datetime) -> str:
    """Format a datetime as a snapshot folder name (converted to UTC)."""
    return moment.astimezone(timezone.utc).strftime(_SNAPSHOT_FORMAT)


def is_snapshot_name(name: str) -> bool:
    """True if *name* is a well-formed snapshot folder name."""
    return bool(_SNAPSHOT_RE.match(name))


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


@dataclass(frozen=True)
class MachineProfile:
    """Where this microscope's calibration + limits live on disk.

    ``programdata_root=None`` resolves to the ``SMART_MICROSCOPY_ROOT`` env var
    if set, else :data:`DEFAULT_PROGRAMDATA_ROOT`. Tests inject an explicit
    ``programdata_root=tmp_path`` to stay hermetic.
    """

    vendor: str = "leica"
    microscope_id: str = "stellaris5_y42h93"
    programdata_root: Path | None = None

    def root(self) -> Path:
        if self.programdata_root is not None:
            return Path(self.programdata_root)
        env = os.environ.get(PROGRAMDATA_ROOT_ENV)
        return Path(env) if env else DEFAULT_PROGRAMDATA_ROOT

    def snapshot_root(self) -> Path:
        return self.root() / self.vendor / self.microscope_id

    def bundled_default_root(self) -> Path:
        return _driver_root() / "defaults"

    def snapshots(self) -> list[Path]:
        """All well-formed snapshot folders under ``snapshot_root``, oldest first.

        Folders whose name is not a valid snapshot stamp (and any files) are
        ignored - they are not snapshots.
        """
        root = self.snapshot_root()
        if not root.is_dir():
            return []
        snaps = [p for p in root.iterdir() if p.is_dir() and is_snapshot_name(p.name)]
        return sorted(snaps, key=lambda p: p.name)

    def latest_snapshot(self) -> Path | None:
        snaps = self.snapshots()
        return snaps[-1] if snaps else None

    def resolve(self, filename: str) -> tuple[Path, bool]:
        """Resolve *filename* to ``(path, is_fallback)``.

        Prefer the newest snapshot's copy; fall back to the bundled default when
        there is no snapshot, or the newest snapshot lacks that file.
        """
        latest = self.latest_snapshot()
        if latest is not None:
            candidate = latest / filename
            if candidate.exists():
                return candidate, False
        return self.bundled_default_root() / filename, True

    def _resolve_logged(self, filename: str, kind: str) -> Path:
        path, is_fallback = self.resolve(filename)
        if is_fallback:
            log.warning(
                "No machine snapshot for %s/%s under %s; using bundled default "
                "%s (%s may be stale - re-calibrate).",
                self.vendor,
                self.microscope_id,
                self.snapshot_root(),
                path,
                kind,
            )
        return path

    def calibration_path(self) -> Path:
        """Active calibration.json (latest snapshot, else bundled default)."""
        return self._resolve_logged(CALIBRATION_FILENAME, "calibration")

    def limits_path(self) -> Path:
        """Active physical limits.json (latest snapshot, else bundled default)."""
        return self._resolve_logged(LIMITS_FILENAME, "limits")

    def new_snapshot_dir(self, moment: datetime) -> Path:
        """Path for a NEW snapshot stamped from *moment*.

        Raises ``ValueError`` when *moment* would not sort strictly after the
        current latest snapshot (backward clock / same-microsecond collision),
        so "newest wins" can never select a stale calibration.
        """
        name = format_snapshot_name(moment)
        latest = self.latest_snapshot()
        if latest is not None and name <= latest.name:
            raise ValueError(
                f"new snapshot {name!r} does not sort after latest "
                f"{latest.name!r}; the system clock moved backward or a "
                "same-microsecond collision occurred"
            )
        return self.snapshot_root() / name

    def _seed_file(self, staging: Path, filename: str, override: dict | None) -> None:
        """Place *filename* in the staging snapshot: the provided dict, else the
        latest snapshot's copy carried forward (bundled default if none)."""
        dest = staging / filename
        if override is not None:
            _write_json(dest, override)
        else:
            src, _ = self.resolve(filename)
            shutil.copy2(src, dest)

    def publish_snapshot(
        self,
        moment: datetime,
        *,
        calibration: dict | None = None,
        limits: dict | None = None,
        notebook_paths: Iterable[str | Path] = (),
    ) -> Path:
        """Publish a new cumulative machine-state snapshot (copy-forward + atomic).

        Seeds the new dated folder by carrying the latest snapshot's
        ``calibration.json`` and ``limits.json`` forward (from the bundled
        default when there is no snapshot), overrides whichever of *calibration*
        / *limits* is provided, copies the given executed notebook(s) in, then
        atomically renames the folder into place. The live snapshot is never
        mutated, so a crash mid-publish cannot corrupt the calibration the driver
        is currently reading.

        *moment* must stamp strictly after the latest snapshot
        (see :meth:`new_snapshot_dir`); callers pass ``datetime.now(timezone.utc)``.
        Domain validation of *calibration* / *limits* is the caller's job.
        """
        target = self.new_snapshot_dir(moment)  # monotonic guard
        root = self.snapshot_root()
        root.mkdir(parents=True, exist_ok=True)
        staging = root / f".{target.name}.partial"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            self._seed_file(staging, CALIBRATION_FILENAME, calibration)
            self._seed_file(staging, LIMITS_FILENAME, limits)
            for nb in notebook_paths:
                nb = Path(nb)
                shutil.copy2(nb, staging / nb.name)
            os.replace(staging, target)  # atomic within snapshot_root
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target


MACHINE = MachineProfile()

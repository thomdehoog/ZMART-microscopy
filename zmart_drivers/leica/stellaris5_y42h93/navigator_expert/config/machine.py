"""Machine-local resolution of this microscope's coordinate-system config.

Runtime coordinate config - the optical calibration, the physical stage
envelope, and how the camera is turned relative to the stage - lives in dated
snapshots under a machine-wide ProgramData root, newest wins. The repo ships
defaults only; the first driver run copies those defaults into ProgramData so
every runtime read is machine-local. Each snapshot dir holds up to three files
(plus named calibration sets and executed notebooks)::

    <programdata_root>/<vendor>/<microscope_id>/<api>/
        <datetime>/
            calibration.json    # legacy/default optical calibration
            calibrations/<name>/calibration.json
                                # named optical calibration sets (per lens setup)
            limits.json         # physical envelope + function gate (schema v1)
            orientation.json    # camera turn relative to the stage (0/90/180/270)
            <executed>.ipynb    # the notebook that produced this adopt
        origin/
            origin.json         # frame zero point (set_origin; session-scoped)

The frame origin is deliberately NOT snapshot state. It is ephemeral operator
state (the current frame zero point), so it lives in its own ``origin/`` folder
next to the snapshots, is written in place by ``set_origin``, and is
session-scoped: the driver does not restore it at connect (a fresh session is
an absolute frame until ``set_origin`` runs). See :meth:`write_origin`.

All runtime values live in ProgramData, not inside the installed code. The
defaults under the driver tree are seed material only; after seeding, reads
return paths under ProgramData.

``limits.json`` is the single function-keyed limits file (decision §7b):
``constraints`` (the ``stage.*`` physical envelope) + ``functions`` (the
per-command gate policy). Both readers - the motion check
(``motion/stage_config``) and the commands gate (``commands/gate``) - read this
one file; there is no separate ``function_limits.json``. Backlash appears in
none of these files: it is a plain motion utility with baked-in defaults
(decision §2b), not machine state.

Each snapshot is a complete, cumulative machine-state record; workflows write
one per adopt by copying the latest snapshot forward and merging their delta.
If ProgramData is empty, or if the newest snapshot predates this complete-file
layout, a new snapshot is created from repo defaults plus any prior machine
values.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PROGRAMDATA_ROOT = Path(r"C:\ProgramData\zmart-microscopy")
PROGRAMDATA_ROOT_ENV = "ZMART_MICROSCOPY_ROOT"

# UTC, microsecond precision, Windows-path-safe, lexical order == chronological.
_SNAPSHOT_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"
_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{6}Z$")

CALIBRATION_FILENAME = "calibration.json"
CALIBRATIONS_DIRNAME = "calibrations"
LIMITS_FILENAME = "limits.json"
ORIENTATION_FILENAME = "orientation.json"
ORIGIN_FILENAME = "origin.json"
CALIBRATION_NAME_ENV = "ZMART_CALIBRATION_NAME"

# Driver-bundled last-known-good defaults, each owned by its subsystem.
# The origin has no bundled default: with none set, the frame is absolute
# stage coordinates.
_BUNDLED_SUBSYSTEM = {
    CALIBRATION_FILENAME: "calibration",
    LIMITS_FILENAME: "limits",
    ORIENTATION_FILENAME: "orientation",
}
_BASELINE_FILES = (CALIBRATION_FILENAME, LIMITS_FILENAME, ORIENTATION_FILENAME)
_SEED_SNAPSHOT_MOMENT = datetime(1970, 1, 1, tzinfo=timezone.utc)

_CALIBRATION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _driver_root() -> Path:
    return Path(__file__).resolve().parents[1]  # navigator_expert/


def format_snapshot_name(moment: datetime) -> str:
    """Format a datetime as a snapshot folder name (converted to UTC)."""
    return moment.astimezone(timezone.utc).strftime(_SNAPSHOT_FORMAT)


def is_snapshot_name(name: str) -> bool:
    """True if *name* is a well-formed snapshot folder name."""
    return bool(_SNAPSHOT_RE.match(name))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def validate_calibration_name(name: str) -> str:
    """Validate a machine-local calibration-set name.

    Names are path segments, not paths. They are intentionally boring so an
    operator-selected lens setup cannot escape ``calibrations/<name>/``.
    """
    value = str(name).strip()
    if not value or value in {".", ".."} or not _CALIBRATION_NAME_RE.match(value):
        raise ValueError(
            "calibration_name must be one path-safe segment using letters, "
            f"numbers, '.', '_' or '-', got {name!r}"
        )
    return value


@dataclass(frozen=True)
class MachineProfile:
    """Where this microscope's calibration + limits live on disk.

    ``programdata_root=None`` resolves to the ``ZMART_MICROSCOPY_ROOT`` env var
    if set, else :data:`DEFAULT_PROGRAMDATA_ROOT`. Tests inject an explicit
    ``programdata_root=tmp_path`` to stay hermetic.
    """

    vendor: str = "leica"
    microscope_id: str = "stellaris5_y42h93"
    api: str = "navigator_expert"
    programdata_root: Path | None = None

    def root(self) -> Path:
        if self.programdata_root is not None:
            return Path(self.programdata_root)
        env = os.environ.get(PROGRAMDATA_ROOT_ENV)
        return Path(env) if env else DEFAULT_PROGRAMDATA_ROOT

    def snapshot_root(self) -> Path:
        return self.root() / self.vendor / self.microscope_id / self.api

    def legacy_snapshot_root(self) -> Path:
        """The pre-api-level snapshot root (vendor/microscope only).

        Snapshots published before the ``<api>`` level was added live here;
        :meth:`migrate_legacy_snapshots` moves them under :meth:`snapshot_root`.
        """
        return self.root() / self.vendor / self.microscope_id

    def _legacy_snapshots(self) -> list[Path]:
        legacy = self.legacy_snapshot_root()
        if not legacy.is_dir():
            return []
        return sorted(
            (p for p in legacy.iterdir() if p.is_dir() and is_snapshot_name(p.name)),
            key=lambda p: p.name,
        )

    def migrate_legacy_snapshots(self) -> list[Path]:
        """One-time move of pre-api-level snapshots under the api level.

        Returns the moved snapshot paths (empty when there is nothing to do).
        A snapshot whose name already exists under the new root is left in
        place with a warning rather than overwritten.
        """
        moved: list[Path] = []
        for src in self._legacy_snapshots():
            target = self.snapshot_root() / src.name
            if target.exists():
                log.warning("legacy snapshot %s also exists at %s; not moving", src, target)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            moved.append(target)
        return moved

    def bundled_default_path(self, filename: str) -> Path:
        """Driver-bundled last-known-good default for *filename*.

        Each subsystem owns its default: ``calibration/defaults/`` and
        ``limits/defaults/``.
        """
        return _driver_root() / _BUNDLED_SUBSYSTEM[filename] / "defaults" / filename

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
        """Resolve *filename* to a ProgramData path.

        The boolean is kept for older callers; it is always ``False`` because
        repo defaults are copied into ProgramData before any runtime path is
        returned.
        """
        snapshot = self.ensure_snapshot()
        path = snapshot / filename
        if not path.exists():
            if filename not in _BUNDLED_SUBSYSTEM:
                raise FileNotFoundError(f"ProgramData file not found: {path}")
            snapshot = self.publish_snapshot(self._next_auto_moment())
            path = snapshot / filename
        return path, False

    def calibration_relpath(self, calibration_name: str) -> Path:
        """Path inside a snapshot for a named calibration set."""
        return (
            Path(CALIBRATIONS_DIRNAME)
            / validate_calibration_name(calibration_name)
            / CALIBRATION_FILENAME
        )

    def resolve_calibration(self, calibration_name: str | None = None) -> tuple[Path, bool]:
        """Resolve the active ProgramData calibration, optionally by lens setup."""
        if calibration_name is None:
            env_name = os.environ.get(CALIBRATION_NAME_ENV)
            if env_name:
                return self.resolve_calibration(env_name)
            return self.resolve(CALIBRATION_FILENAME)

        rel = self.calibration_relpath(calibration_name)
        snapshot = self.latest_snapshot()
        if snapshot is not None:
            snapshot = self.ensure_snapshot()
            candidate = snapshot / rel
            if candidate.exists():
                return candidate, False
        default_calibration = json.loads(
            self.bundled_default_path(CALIBRATION_FILENAME).read_text(encoding="utf-8")
        )
        snapshot = self.publish_snapshot(
            self._next_auto_moment(),
            calibration=default_calibration,
            calibration_name=calibration_name,
        )
        return snapshot / rel, False

    def require_machine_local(self, filename: str, kind: str) -> Path:
        """Resolve *filename* as machine-local ProgramData state."""
        path, _ = self.resolve(filename)
        return path

    def calibration_path(self, calibration_name: str | None = None) -> Path:
        """Active ProgramData calibration.json.

        Pass ``calibration_name`` to select a named lens/session calibration
        under ``calibrations/<name>/calibration.json``. With no name, the
        ``ZMART_CALIBRATION_NAME`` environment variable can select one; otherwise
        the legacy/default flat ``calibration.json`` is used.
        """
        path, _ = self.resolve_calibration(calibration_name)
        return path

    def limits_path(self) -> Path:
        """Active physical limits.json under ProgramData."""
        path, _ = self.resolve(LIMITS_FILENAME)
        return path

    def orientation_path(self) -> Path:
        """Active orientation.json under ProgramData."""
        path, _ = self.resolve(ORIENTATION_FILENAME)
        return path

    # --- origin: the operator-set frame zero point -----------------------
    #
    # The origin is ephemeral operator state, not immutable machine
    # calibration, so it lives in its own ``origin/`` folder next to the dated
    # snapshots — never inside them. It is session-scoped: the driver does NOT
    # restore it at connect. ``set_origin`` writes it (and sets the session's
    # in-memory frame); it is kept on disk only as a record of the last origin
    # captured. ``"origin"`` is not a valid snapshot stamp, so the snapshot
    # listing ignores this folder.

    def origin_dir(self) -> Path:
        """The folder holding this microscope's frame origin."""
        return self.snapshot_root() / "origin"

    def origin_path(self) -> Path:
        """Path to the persisted frame origin file."""
        return self.origin_dir() / ORIGIN_FILENAME

    def read_origin(self) -> dict | None:
        """The last persisted frame origin, or None when never set.

        Not called at connect (the frame is session-scoped and starts
        absolute); provided for tools and explicit ``get``-style callers.
        """
        path = self.origin_path()
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_origin(self, payload: dict) -> Path:
        """Persist the frame origin into the ``origin/`` folder (atomic replace).

        Independent of the dated snapshots, so ``set_origin`` always succeeds
        even before any calibration snapshot exists. Returns the written path.
        """
        path = self.origin_path()
        tmp = path.with_suffix(".json.tmp")
        _write_json(tmp, payload)
        os.replace(tmp, path)
        return path

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

    def _next_auto_moment(self) -> datetime:
        """Timestamp for internal seed/repair snapshots.

        Synthetic defaults should not outrank a later notebook adopt that uses
        an explicit timestamp, so the first seed is deterministic and old.
        Repairs sort one microsecond after the current latest snapshot.
        """
        latest = self.latest_snapshot()
        if latest is None:
            return _SEED_SNAPSHOT_MOMENT
        latest_moment = datetime.strptime(latest.name, _SNAPSHOT_FORMAT).replace(
            tzinfo=timezone.utc
        )
        return latest_moment + timedelta(microseconds=1)

    def _baseline_missing(self, snapshot: Path) -> list[str]:
        return [filename for filename in _BASELINE_FILES if not (snapshot / filename).exists()]

    def ensure_snapshot(self) -> Path:
        """Return a complete ProgramData snapshot, seeding defaults if needed."""
        latest = self.latest_snapshot()
        if latest is not None and not self._baseline_missing(latest):
            return latest
        return self.publish_snapshot(self._next_auto_moment())

    def _seed_file(
        self,
        staging: Path,
        filename: str,
        override: dict | None,
        *,
        prior: Path | None,
    ) -> None:
        """Place *filename* in staging: override, prior ProgramData, or default."""
        dest = staging / filename
        if override is not None:
            _write_json(dest, override)
            return
        if prior is not None and (prior / filename).exists():
            src = prior / filename
        else:
            src = self.bundled_default_path(filename)
        shutil.copy2(src, dest)

    def _seed_calibrations_dir(self, staging: Path, *, prior: Path | None) -> None:
        """Carry every named calibration set forward from the latest snapshot."""
        if prior is None:
            return
        src = prior / CALIBRATIONS_DIRNAME
        if src.is_dir():
            shutil.copytree(src, staging / CALIBRATIONS_DIRNAME, dirs_exist_ok=True)

    def publish_snapshot(
        self,
        moment: datetime,
        *,
        calibration: dict | None = None,
        calibration_name: str | None = None,
        limits: dict | None = None,
        orientation: dict | None = None,
        notebook_paths: Iterable[str | Path] = (),
    ) -> Path:
        """Publish a new cumulative machine-state snapshot (copy-forward + atomic).

        Seeds the new dated folder by carrying the latest ProgramData snapshot's
        baseline files forward, or copying the repo defaults into ProgramData
        when no prior file exists. Overrides whichever of *calibration* /
        *limits* / *orientation* is provided, copies the given executed
        notebook(s) in, then atomically renames the folder into place. The
        frame origin is not snapshot state and is never read from or written
        into a snapshot — it lives in its own ``origin/`` folder (see
        :meth:`write_origin`). The live snapshot is never mutated, so a crash
        mid-publish cannot corrupt the config the driver is currently reading.

        *moment* must stamp strictly after the latest snapshot
        (see :meth:`new_snapshot_dir`).
        Domain validation of the payloads is the caller's job.
        """
        prior = self.latest_snapshot()
        target = self.new_snapshot_dir(moment)  # monotonic guard
        root = self.snapshot_root()
        root.mkdir(parents=True, exist_ok=True)
        staging = root / f".{target.name}.partial"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            self._seed_file(
                staging,
                CALIBRATION_FILENAME,
                calibration if calibration_name is None else None,
                prior=prior,
            )
            self._seed_calibrations_dir(staging, prior=prior)
            if calibration is not None and calibration_name is not None:
                _write_json(staging / self.calibration_relpath(calibration_name), calibration)
            self._seed_file(staging, LIMITS_FILENAME, limits, prior=prior)
            self._seed_file(staging, ORIENTATION_FILENAME, orientation, prior=prior)
            # The origin is not snapshot state — it lives in its own origin/
            # folder (see write_origin) and is not carried into snapshots.
            for nb in notebook_paths:
                nb = Path(nb)
                shutil.copy2(nb, staging / nb.name)
            os.replace(staging, target)  # atomic within snapshot_root
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target


MACHINE = MachineProfile()

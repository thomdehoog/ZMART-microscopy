"""Machine-local resolution of this microscope's coordinate-system config.

Each subsystem owns an independent, append-only timestamp tree under the
microscope API root::

    <programdata_root>/<vendor>/<microscope_id>/<api>/
        limits/<datetime>/
            limits.json
            notebook/set_limits_<datetime>.ipynb
            data/
                template/<saved experiment>.{xml,rgn,lrp}
        calibration/
            <datetime>/
                calibration.json
                calibrations/<name>/calibration.json
                <executed>.ipynb
            <session-id>/
                calibration.json
                <acquisition-name>/
                    data/
                    reports/
        orientation/
            <datetime>/
                orientation.json
                data/notebook/set_orientation.ipynb
            <session-id>/
                data/
                reports/
                configs/
        origin/<datetime>/
            origin.json

The newest timestamp in each subsystem wins independently. Publishing limits
does not duplicate calibration or orientation, and every origin change keeps
its own immutable record. The frame origin remains session-scoped: the driver
does not restore it at connect.

Operator-published runtime values live in ProgramData. Bundled defaults stay
inside the installed code and are used directly only when no machine limits
snapshot exists or a published file cannot be loaded.

``limits.json`` is deliberately flat: ``x_um``, ``y_um``, both Z ranges, the
objective slot policy, and one entry per configurable setter. Each constraint
explicitly says ``range`` or ``allowed``; ``[]`` means unrestricted.
There is no metadata wrapper, hidden marker, or separate
``function_limits.json``. A ProgramData ``limits.json`` exists only after an
operator publishes it, so its location is the provenance. Backlash is a motion
utility with baked-in defaults, not machine state.

Flat timestamp folders from older releases are migration input. They remain
untouched while their newest values are copied into the corresponding
subsystem trees. Calibration and orientation can seed ProgramData from bundled
defaults; limits cannot, because mere presence now means operator-published.

``<datetime>`` is UTC with microsecond precision, formatted so it is both a
legal Windows path segment (no colons) and lexicographically == chronologically
sortable::

    2026-07-01T14-30-00-123456Z

The active snapshot for a subsystem is its lexical max. A new snapshot must
stamp strictly later than the latest snapshot in that same subsystem, so a
backward system clock or same-microsecond re-run cannot make fresh config stale.
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
# Read only while migrating snapshots written by releases that used a hidden
# approval sentinel. New subsystem snapshots never create or copy this file.
LEGACY_LIMITS_MACHINE_MARKER = ".limits-machine"
ORIENTATION_FILENAME = "orientation.json"
ORIGIN_FILENAME = "origin.json"
CALIBRATION_NAME_ENV = "ZMART_CALIBRATION_NAME"
SUBSYSTEMS = ("limits", "calibration", "orientation", "origin")

# Driver-bundled last-known-good defaults, each owned by its subsystem.
# The origin has no bundled default: with none set, the frame is absolute
# stage coordinates.
_BUNDLED_SUBSYSTEM = {
    CALIBRATION_FILENAME: "calibration",
    LIMITS_FILENAME: "limits",
    ORIENTATION_FILENAME: "orientation",
}
_SUBSYSTEM_FILENAME = {subsystem: filename for filename, subsystem in _BUNDLED_SUBSYSTEM.items()}
_SUBSYSTEM_FILENAME["origin"] = ORIGIN_FILENAME
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
        # Payload builders define an operator-readable order. In particular,
        # limits.json starts with X/Y/Z ranges before optional setter limits.
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")


def _io_path(path: Path) -> str | Path:
    """Use an extended-length path for deep snapshot evidence on Windows."""
    if os.name != "nt":
        return path
    absolute = str(path.absolute())
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


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

    def ensure_layout(self) -> Path:
        """Create the API root and its subsystem directories if absent."""
        root = self.snapshot_root()
        for subsystem in SUBSYSTEMS:
            (root / subsystem).mkdir(parents=True, exist_ok=True)
        return root

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
        """Copy pre-api-level snapshots under the api level for migration.

        Returns the copied snapshot paths (empty when there is nothing to do).
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
            shutil.copytree(src, target)
            moved.append(target)
        return moved

    def bundled_default_path(self, filename: str) -> Path:
        """Driver-bundled last-known-good default for *filename*.

        Each subsystem owns its default: ``calibration/defaults/`` and
        ``limits/defaults/``.
        """
        return _driver_root() / _BUNDLED_SUBSYSTEM[filename] / "defaults" / filename

    def subsystem_root(self, subsystem: str) -> Path:
        """Root containing timestamp folders for one config subsystem."""
        if subsystem not in SUBSYSTEMS:
            raise ValueError(f"unknown machine-config subsystem {subsystem!r}")
        return self.snapshot_root() / subsystem

    def _flat_snapshots(self) -> list[Path]:
        """Old API-level snapshots, retained as migration input."""
        root = self.snapshot_root()
        if not root.is_dir():
            return []
        return sorted(
            (path for path in root.iterdir() if path.is_dir() and is_snapshot_name(path.name)),
            key=lambda path: path.name,
        )

    def snapshots(self, subsystem: str) -> list[Path]:
        """Timestamp folders for *subsystem*, oldest first."""
        root = self.subsystem_root(subsystem)
        if not root.is_dir():
            return []
        required = _SUBSYSTEM_FILENAME[subsystem]
        return sorted(
            (
                path
                for path in root.iterdir()
                if path.is_dir()
                and is_snapshot_name(path.name)
                and (subsystem != "orientation" or (path / required).is_file())
            ),
            key=lambda path: path.name,
        )

    def latest_snapshot(self, subsystem: str) -> Path | None:
        snaps = self.snapshots(subsystem)
        return snaps[-1] if snaps else None

    @staticmethod
    def _notebook_matches(subsystem: str, path: Path) -> bool:
        name = path.stem.lower()
        if subsystem == "limits":
            return "limit" in name
        if subsystem == "orientation":
            return "orientation" in name
        if subsystem == "calibration":
            return "limit" not in name and "orientation" not in name
        return False

    def _migrate_flat_subsystem(self, subsystem: str, source: Path) -> Path:
        """Copy one old flat snapshot into a subsystem timestamp folder."""
        target = self.subsystem_root(subsystem) / source.name
        staging = target.parent / f".{target.name}.partial"
        target.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            filename = _SUBSYSTEM_FILENAME[subsystem]
            shutil.copy2(source / filename, staging / filename)
            if subsystem == "calibration":
                named = source / CALIBRATIONS_DIRNAME
                if named.is_dir():
                    shutil.copytree(named, staging / CALIBRATIONS_DIRNAME)
            for notebook in source.glob("*.ipynb"):
                if self._notebook_matches(subsystem, notebook):
                    from ..notebook_support import archive_notebook

                    archive_notebook(
                        notebook,
                        staging,
                        directory="notebook"
                        if subsystem == "limits"
                        else Path("data") / "notebook",
                    )
            os.replace(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target

    def publish_snapshot(
        self,
        moment: datetime,
        *,
        calibration: dict | None = None,
        calibration_name: str | None = None,
        limits: dict | None = None,
        orientation: dict | None = None,
        archive_paths: Iterable[str | Path] = (),
        notebook_paths: Iterable[str | Path] = (),
    ) -> Path:
        """Publish exactly one subsystem delta into its timestamp tree."""
        updates = (
            ("calibration", calibration),
            ("limits", limits),
            ("orientation", orientation),
        )
        selected = [(subsystem, payload) for subsystem, payload in updates if payload is not None]
        if len(selected) != 1:
            raise ValueError("publish_snapshot requires exactly one subsystem payload")
        self.migrate_flat_snapshots()
        subsystem, payload = selected[0]
        if calibration_name is not None and subsystem != "calibration":
            raise ValueError("calibration_name requires a calibration payload")
        return self._publish_subsystem_snapshot(
            moment,
            subsystem,
            payload=payload,
            calibration_name=calibration_name,
            archive_paths=archive_paths,
            notebook_paths=notebook_paths,
        )

    def migrate_flat_snapshots(self) -> dict[str, Path]:
        """Copy newest old-layout values into independent subsystem trees."""
        self.migrate_legacy_snapshots()
        flat = self._flat_snapshots()
        migrated: dict[str, Path] = {}
        for subsystem in ("limits", "calibration", "orientation"):
            filename = _SUBSYSTEM_FILENAME[subsystem]
            source = next(
                (
                    path
                    for path in reversed(flat)
                    if (path / filename).is_file()
                    and (subsystem != "limits" or (path / LEGACY_LIMITS_MACHINE_MARKER).is_file())
                ),
                None,
            )
            latest = self.latest_snapshot(subsystem)
            if source is not None and (latest is None or source.name > latest.name):
                migrated[subsystem] = self._migrate_flat_subsystem(subsystem, source)

        origin_root = self.subsystem_root("origin")
        old_origin = origin_root / ORIGIN_FILENAME
        if old_origin.is_file():
            moment = datetime.fromtimestamp(old_origin.stat().st_mtime, tz=timezone.utc)
            latest = self.latest_snapshot("origin")
            if latest is None or format_snapshot_name(moment) > latest.name:
                target = self.new_snapshot_dir(moment, "origin")
                staging = target.parent / f".{target.name}.partial"
                if staging.exists():
                    shutil.rmtree(staging)
                staging.mkdir(parents=True)
                try:
                    shutil.copy2(old_origin, staging / ORIGIN_FILENAME)
                    os.replace(staging, target)
                except BaseException:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise
                migrated["origin"] = target
        return migrated

    def resolve(self, filename: str) -> tuple[Path, bool]:
        """Resolve a baseline filename to its newest subsystem snapshot."""
        try:
            subsystem = _BUNDLED_SUBSYSTEM[filename]
        except KeyError as exc:
            raise FileNotFoundError(f"unknown ProgramData config file: {filename}") from exc
        snapshot = self.ensure_snapshot(subsystem)
        return snapshot / filename, False

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

        self.migrate_flat_snapshots()
        rel = self.calibration_relpath(calibration_name)
        snapshot = self.latest_snapshot("calibration")
        if snapshot is not None:
            candidate = snapshot / rel
            if candidate.exists():
                return candidate, False
        default_calibration = json.loads(
            self.bundled_default_path(CALIBRATION_FILENAME).read_text(encoding="utf-8")
        )
        if calibration_name is not None:
            # A fresh NAMED set starts with no objectives. An operator creates
            # a named set precisely to establish their own reference
            # objective; seeding it with the bundled placeholder numbers
            # would lock the reference to the placeholder's arbitrary choice
            # and make "start a new calibration_name" advice impossible to
            # follow. The first measured pair anchors the origin instead.
            default_calibration = {
                "objectives": {},
                "schema_version": default_calibration["schema_version"],
            }
        snapshot = self.publish_snapshot(
            self._next_auto_moment("calibration"),
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
    # Origin records have their own timestamp tree but remain session-scoped:
    # connect never reapplies the newest record automatically.

    def origin_dir(self) -> Path:
        """Root containing this microscope's frame-origin history."""
        return self.subsystem_root("origin")

    def origin_path(self) -> Path:
        """Newest persisted frame origin, or a non-existent placeholder path."""
        self.migrate_flat_snapshots()
        latest = self.latest_snapshot("origin")
        return (latest / ORIGIN_FILENAME) if latest else (self.origin_dir() / ORIGIN_FILENAME)

    def read_origin(self) -> dict | None:
        """The last persisted frame origin, or None when never set.

        Not called at connect (the frame is session-scoped and starts
        absolute); provided for tools and explicit ``get``-style callers.
        """
        path = self.origin_path()
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_origin(self, payload: dict, *, moment: datetime | None = None) -> Path:
        """Append one timestamped frame-origin record and return its JSON path."""
        self.migrate_flat_snapshots()
        if moment is None:
            moment = datetime.now(timezone.utc)
            latest = self.latest_snapshot("origin")
            if latest is not None and format_snapshot_name(moment) <= latest.name:
                moment = self._next_auto_moment("origin")
        target = self.new_snapshot_dir(moment, "origin")
        staging = target.parent / f".{target.name}.partial"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            _write_json(staging / ORIGIN_FILENAME, payload)
            os.replace(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target / ORIGIN_FILENAME

    def new_snapshot_dir(self, moment: datetime, subsystem: str) -> Path:
        """Path for a new snapshot, monotonic within one subsystem."""
        name = format_snapshot_name(moment)
        latest = self.latest_snapshot(subsystem)
        if latest is not None and name <= latest.name:
            raise ValueError(
                f"new {subsystem} snapshot {name!r} does not sort after latest "
                f"{latest.name!r}; the system clock moved backward or a "
                "same-microsecond collision occurred"
            )
        return self.subsystem_root(subsystem) / name

    def _next_auto_moment(self, subsystem: str) -> datetime:
        """Timestamp for a subsystem seed or repair snapshot."""
        latest = self.latest_snapshot(subsystem)
        if latest is None:
            return _SEED_SNAPSHOT_MOMENT
        latest_moment = datetime.strptime(latest.name, _SNAPSHOT_FORMAT).replace(
            tzinfo=timezone.utc
        )
        return latest_moment + timedelta(microseconds=1)

    def ensure_snapshot(self, subsystem: str) -> Path:
        """Return a complete subsystem snapshot, migrating or seeding as needed."""
        if subsystem == "origin":
            raise ValueError("origin has no default snapshot")
        self.migrate_flat_snapshots()
        latest = self.latest_snapshot(subsystem)
        filename = _SUBSYSTEM_FILENAME[subsystem]
        if latest is not None and (latest / filename).is_file():
            return latest
        if subsystem == "limits":
            raise FileNotFoundError(
                "no operator-published ProgramData limits.json exists; publish one "
                "with limits/notebooks/set_limits.ipynb"
            )
        return self._publish_subsystem_snapshot(
            self._next_auto_moment(subsystem),
            subsystem,
            payload=None,
            calibration_name=None,
            notebook_paths=(),
        )

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

    def _publish_subsystem_snapshot(
        self,
        moment: datetime,
        subsystem: str,
        *,
        payload: dict | None,
        calibration_name: str | None = None,
        archive_paths: Iterable[str | Path] = (),
        notebook_paths: Iterable[str | Path] = (),
    ) -> Path:
        """Publish one subsystem snapshot using copy-forward only within it."""
        prior = self.latest_snapshot(subsystem)
        target = self.new_snapshot_dir(moment, subsystem)
        root = self.subsystem_root(subsystem)
        root.mkdir(parents=True, exist_ok=True)
        staging = root / f".{target.name}.partial"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            filename = _SUBSYSTEM_FILENAME[subsystem]
            self._seed_file(
                staging,
                filename,
                payload if calibration_name is None else None,
                prior=prior,
            )
            if subsystem == "calibration":
                self._seed_calibrations_dir(staging, prior=prior)
                if payload is not None and calibration_name is not None:
                    _write_json(staging / self.calibration_relpath(calibration_name), payload)
            for source in archive_paths:
                source = Path(source)
                destination = staging / source.name
                if destination.exists():
                    raise FileExistsError(
                        f"snapshot archive destination already exists: {destination}"
                    )
                if source.is_dir():
                    shutil.copytree(_io_path(source), _io_path(destination))
                else:
                    shutil.copy2(_io_path(source), _io_path(destination))
            for nb in notebook_paths:
                from ..notebook_support import archive_notebook

                nb = Path(nb)
                archive_notebook(
                    nb,
                    staging,
                    directory="notebook" if subsystem == "limits" else Path("data") / "notebook",
                )
            os.replace(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target


MACHINE = MachineProfile()

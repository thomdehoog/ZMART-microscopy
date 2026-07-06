"""Machine-local resolution of this microscope's coordinate-system config.

Runtime coordinate config - the optical calibration, the physical stage
envelope + calibrated backlash, and the operator-set frame origin - lives in
dated snapshots under a machine-wide ProgramData root, newest wins. Each
snapshot dir holds exactly three files (plus the executed notebook)::

    <programdata_root>/<vendor>/<microscope_id>/<api>/<datetime>/
        calibration.json    # optical calibration (image<->stage, per-objective)
        limits.json         # physical envelope + function gate + backlash (schema v1)
        origin.json         # frame zero point (set_origin; updated in place)
        <executed>.ipynb    # the notebook that produced this adopt

``limits.json`` is the single function-keyed limits file (decision §7b):
``constraints`` (the ``stage.*`` physical envelope) + ``functions`` (the
per-command gate policy) + a ``backlash`` block. Both readers - the motion
check (``motion/stage_config``) and the commands gate (``commands/gate``) -
read this one file; there is no separate ``function_limits.json``.

Each snapshot is a complete, cumulative machine-state record; the calibration
workflow writes one per adopt by copying the latest snapshot forward and
merging its delta. ``origin.json`` is the one exception to snapshot
immutability: it is ephemeral operator state (the current frame zero point),
written into the *newest* snapshot in place by ``set_origin`` and carried
forward on adopt, so it stays the truth until set again.

When no snapshot exists (fresh machine, or a wiped ProgramData tree), what
happens depends on the file:

- ``calibration.json`` falls back - loudly - to the bundled
  ``calibration/defaults/calibration.json`` on READ
  (:meth:`calibration_path`): a real last-known-good calibration for this
  microscope (never an identity/zero placeholder), so read/compensation paths
  stay usable while warning that a re-calibration is due. Publishing, however,
  never seeds calibration from the bundled template (decision §7b): a limits
  adopt writes only ``limits.json`` and carries a *real* prior calibration
  forward if one exists, never mints one from the template.
- ``limits.json`` does NOT fall back for enforcement. The bundled copy under
  ``limits/defaults/`` is a TEMPLATE only - a bundled envelope can be the
  wrong machine's envelope, which breaks safety rather than providing it. The
  connect-time limits handshake (``commands/gate.py``) refuses the fallback
  and every mutating command then refuses until the machine-local file exists;
  the file factory is ``limits/notebooks/set_stage_limits.ipynb``.
  ``resolve()`` still returns the bundled path with ``is_fallback=True`` so
  callers (tests, template tooling) can reach the template deliberately.

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

DEFAULT_PROGRAMDATA_ROOT = Path(r"C:\ProgramData\zmart-microscopy")
PROGRAMDATA_ROOT_ENV = "ZMART_MICROSCOPY_ROOT"

# UTC, microsecond precision, Windows-path-safe, lexical order == chronological.
_SNAPSHOT_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"
_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{6}Z$")

CALIBRATION_FILENAME = "calibration.json"
LIMITS_FILENAME = "limits.json"
ORIGIN_FILENAME = "origin.json"

# Driver-bundled last-known-good defaults, each owned by its subsystem.
# The origin has no bundled default: with none set, the frame is absolute
# stage coordinates.
_BUNDLED_SUBSYSTEM = {
    CALIBRATION_FILENAME: "calibration",
    LIMITS_FILENAME: "limits",
}


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
        """Resolve *filename* to ``(path, is_fallback)`` - explicit provenance.

        Prefer the newest snapshot's copy; fall back to the bundled default when
        there is no snapshot, or the newest snapshot lacks that file. Callers
        that enforce safety must check ``is_fallback`` and refuse the bundled
        copy (see :meth:`require_machine_local`).
        """
        latest = self.latest_snapshot()
        if latest is not None:
            candidate = latest / filename
            if candidate.exists():
                return candidate, False
        return self.bundled_default_path(filename), True

    def require_machine_local(self, filename: str, kind: str) -> Path:
        """Resolve *filename* strictly: the machine-local snapshot copy or raise.

        The no-fallback rule for limits enforcement: a bundled default that
        silently applies can be the wrong machine's envelope, so enforcement
        refuses it. The error names the location tried and the notebook that
        creates the machine-local file.
        """
        path, is_fallback = self.resolve(filename)
        if is_fallback:
            latest = self.latest_snapshot()
            tried = (latest / filename) if latest is not None else self.snapshot_root()
            raise RuntimeError(
                f"no machine-local {filename} for {kind}: tried {tried} "
                f"(newest snapshot under {self.snapshot_root()}). The bundled "
                f"{path} is a TEMPLATE and is never trusted for enforcement. "
                f"Create the machine-local file with "
                f"limits/notebooks/set_stage_limits.ipynb, then reconnect."
            )
        return path

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
            if self._legacy_snapshots():
                log.warning(
                    "Pre-api-level snapshots exist at %s; run "
                    "MachineProfile.migrate_legacy_snapshots() once to move "
                    "them under %s.",
                    self.legacy_snapshot_root(),
                    self.snapshot_root(),
                )
        return path

    def calibration_path(self) -> Path:
        """Active calibration.json (latest snapshot, else bundled default)."""
        return self._resolve_logged(CALIBRATION_FILENAME, "calibration")

    def limits_path(self) -> Path:
        """Active physical limits.json (latest snapshot, else bundled default)."""
        return self._resolve_logged(LIMITS_FILENAME, "limits")

    # --- origin: the operator-set frame zero point -----------------------

    def read_origin(self) -> dict | None:
        """The persisted frame origin, or None (no snapshot / never set)."""
        latest = self.latest_snapshot()
        if latest is None:
            return None
        path = latest / ORIGIN_FILENAME
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_origin(self, payload: dict) -> Path | None:
        """Persist the frame origin into the newest snapshot (atomic replace).

        Returns the written path, or None when no snapshot exists yet - the
        origin cannot outlive machine state that was never established, so
        the caller keeps it in memory and says so.
        """
        latest = self.latest_snapshot()
        if latest is None:
            return None
        path = latest / ORIGIN_FILENAME
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

    def _seed_file(
        self, staging: Path, filename: str, override: dict | None, *, bundled_ok: bool = True
    ) -> None:
        """Place *filename* in the staging snapshot: the provided dict, else the
        latest snapshot's copy carried forward (bundled default if none and
        ``bundled_ok``). With ``bundled_ok=False`` and no machine-local source,
        the file is omitted — neither ``limits.json`` nor ``calibration.json``
        is minted from the bundled template by a side-effect publish (§7b);
        only an explicit override (a calibration adopt, or the set_stage_limits
        notebook for limits) creates one, or a real machine-local prior is
        carried forward."""
        dest = staging / filename
        if override is not None:
            _write_json(dest, override)
            return
        src, is_fallback = self.resolve(filename)
        if is_fallback and not bundled_ok:
            return
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
        ``calibration.json`` and ``limits.json`` forward, overrides whichever
        of *calibration* / *limits* is provided, carries a persisted
        ``origin.json`` forward when one exists (so an adopt never silently
        drops the operator's frame origin), copies the given executed
        notebook(s) in, then atomically renames the folder into place. The
        live snapshot is never mutated, so a crash mid-publish cannot corrupt
        the calibration the driver is currently reading.

        Seeding provenance (decision §7b): NEITHER file seeds from the bundled
        template. With no machine-local prior and no override, the file is
        omitted — so a limits adopt can never mint an enforceable envelope out
        of the bundled template (the set_stage_limits notebook is the only
        factory), and it never mints a calibration.json either (a real prior
        calibration is carried forward if present; otherwise calibration stays
        the loud in-memory READ fallback until an explicit calibration adopt).

        *moment* must stamp strictly after the latest snapshot
        (see :meth:`new_snapshot_dir`); callers pass ``datetime.now(timezone.utc)``.
        Domain validation of the payloads is the caller's job.
        """
        target = self.new_snapshot_dir(moment)  # monotonic guard
        root = self.snapshot_root()
        root.mkdir(parents=True, exist_ok=True)
        staging = root / f".{target.name}.partial"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            self._seed_file(staging, CALIBRATION_FILENAME, calibration, bundled_ok=False)
            self._seed_file(staging, LIMITS_FILENAME, limits, bundled_ok=False)
            prior = self.latest_snapshot()
            if prior is not None and (prior / ORIGIN_FILENAME).exists():
                shutil.copy2(prior / ORIGIN_FILENAME, staging / ORIGIN_FILENAME)
            for nb in notebook_paths:
                nb = Path(nb)
                shutil.copy2(nb, staging / nb.name)
            os.replace(staging, target)  # atomic within snapshot_root
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target


MACHINE = MachineProfile()

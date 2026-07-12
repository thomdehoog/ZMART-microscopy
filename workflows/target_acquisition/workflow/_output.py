"""Small, workflow-owned output layout helpers.

The workflow owns experiment/acquisition folders.  Drivers own image
filenames and return the files they saved; this module only moves those files,
without renaming them, into the acquisition's ``data`` folder.
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._records import record_channel_paths

_NAME_RE = re.compile(r"^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*$")
_HASH_RE = re.compile(r"^[0-9a-z]{6}$")
_CREATE_ATTEMPTS = 16


@dataclass(frozen=True)
class AcquisitionOutput:
    """One workflow acquisition-type directory."""

    root: Path
    data: Path


def _validate_name(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise ValueError(
            f"{field} must contain only letters/digits separated by '-' or '_', got {value!r}"
        )
    return value


def _validate_hash(value: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise ValueError(f"hash6 must be exactly 6 lowercase base36 characters, got {value!r}")
    return value


def _new_hash() -> str:
    return uuid.uuid4().hex[:6]


def _create_hashed_dir(parent: Path, name: str, hash6: str | None) -> tuple[str, Path]:
    parent.mkdir(parents=True, exist_ok=True)
    if hash6 is not None:
        value = _validate_hash(hash6)
        path = parent / f"{name}_{value}"
        path.mkdir(parents=False, exist_ok=False)
        return value, path

    for _ in range(_CREATE_ATTEMPTS):
        value = _new_hash()
        path = parent / f"{name}_{value}"
        try:
            path.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            continue
        return value, path
    raise RuntimeError(f"could not allocate a unique output directory for {name!r} under {parent}")


def prepare_experiment(output_root: Any, experiment: str, *, hash6: str | None = None) -> Path:
    """Create and return ``<output_root>/<experiment>_<hash6>``."""

    name = _validate_name(experiment, field="experiment")
    _hash, path = _create_hashed_dir(Path(output_root).expanduser().resolve(), name, hash6)
    return path


def prepare_acquisition(
    experiment_root: Any,
    acquisition_type: str,
) -> AcquisitionOutput:
    """Create ``<experiment>/<acquisition_type>/data``."""

    name = _validate_name(acquisition_type, field="acquisition_type")
    root = Path(experiment_root) / name
    root.mkdir(parents=True, exist_ok=True)
    data = root / "data"
    data.mkdir(exist_ok=True)
    return AcquisitionOutput(root=root, data=data)


def position_label(
    position: int,
    *,
    carrier: int = 0,
    compartment: int = 0,
    group: int = 0,
    view: int = 0,
) -> str:
    """Return the canonical workflow location label (time/channel/z are planes)."""

    fields = {
        "carrier": (carrier, 2),
        "compartment": (compartment, 6),
        "group": (group, 6),
        "position": (position, 6),
        "view": (view, 2),
    }
    for name, (value, width) in fields.items():
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 10**width:
            raise ValueError(f"{name} must be a whole number from 0 through {10**width - 1}")
    return f"K{carrier:02d}_M{compartment:06d}_G{group:06d}_P{position:06d}_V{view:02d}"


def move_record_images(record: dict, data_dir: Any) -> dict:
    """Move a driver's returned images unchanged and update its record paths.

    Which files a driver saved is read through :func:`record_channel_paths` --
    the same driver-agnostic reader the rest of the workflow uses -- so this
    step works for any driver's record shape (a plain ``images`` or
    ``image_files`` list, a Leica-style ``planes`` manifest, or a
    mesoSPIM-style plain plane count) rather than only the ones that happen
    to fill in ``images``.

    Every source and destination is validated before the first move.  If a
    later move fails, already moved files are rolled back to their original
    paths so one multi-plane record is never half-relocated.
    """

    # The single source of truth for the saved images, plus every path the
    # record records under its own keys, so all of them are remapped after the
    # move. ``dict.fromkeys`` keeps insertion order while dropping duplicates.
    sources = dict.fromkeys(
        Path(value) for value in record_channel_paths(record, context="acquire record")
    )
    for key in ("images", "image_files"):
        values = record.get(key)
        if isinstance(values, list):
            sources.update(dict.fromkeys(Path(value) for value in values))
    planes = record.get("planes")
    if isinstance(planes, (list, tuple)):
        # Only a manifest carries paths; a plain plane count has none to remap.
        sources.update(dict.fromkeys(Path(plane["path"]) for plane in planes))
    sources = list(sources)

    destination = Path(data_dir)
    destination.mkdir(parents=True, exist_ok=True)

    moves = [(source, destination / source.name) for source in sources]
    names = [target.name for _, target in moves]
    if len(names) != len(set(names)):
        raise RuntimeError("acquire returned different image paths with the same filename")
    for source, target in moves:
        if not source.is_file():
            raise FileNotFoundError(f"acquired image does not exist: {source}")
        if target.exists():
            raise FileExistsError(f"refusing to replace an existing acquisition image: {target}")

    moved: list[tuple[Path, Path]] = []
    try:
        for source, target in moves:
            shutil.move(str(source), str(target))
            moved.append((source, target))
    except Exception:
        for source, target in reversed(moved):
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        raise

    mapped = {str(source): str(target) for source, target in moves}
    for key in ("images", "image_files"):
        values = record.get(key)
        if isinstance(values, list):
            record[key] = [mapped[str(Path(value))] for value in values]
    if isinstance(planes, (list, tuple)):
        for plane in planes:
            plane["path"] = mapped[str(Path(plane["path"]))]
    return record

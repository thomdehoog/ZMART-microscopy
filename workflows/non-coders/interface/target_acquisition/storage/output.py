"""Small, workflow-owned output layout helpers.

The workflow owns experiment/acquisition folders, and gives a driver the
acquisition's folder to save in. Inside it the driver owns the layout and the
filenames, and returns the files it saved; this module only files those a
driver saved in a place of its own, in the acquisition's folder, keeping the
layout and the names it gave them.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

_NAME_RE = re.compile(r"^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*$")
_HASH_RE = re.compile(r"^[0-9a-z]{6}$")
_CREATE_ATTEMPTS = 16


def checked_name(value: str, *, field: str) -> str:
    """``value`` itself, when it can safely become one folder name; otherwise a ValueError.

    Letters and digits, joined by single ``-`` or ``_``. Such a name can never
    be a path: it has no slash, no backslash, no drive letter and no ``..``,
    so a folder made from it always stays inside the folder it is joined
    onto. Names that arrive from the page are checked with this before they
    reach the disk, because some of them decide what is deleted.
    """
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise ValueError(
            f"the {field} {value!r} cannot be used as a folder name; it may hold only letters "
            "and digits, joined by single '-' or '_'"
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

    name = checked_name(experiment, field="experiment")
    _hash, path = _create_hashed_dir(Path(output_root).expanduser().resolve(), name, hash6)
    return path


def prepare_acquisition(experiment_root: Any, acquisition_type: str) -> Path:
    """Create and return ``<experiment>/<acquisition_type>``, the folder a driver saves the acquisition in."""

    folder = Path(experiment_root) / checked_name(acquisition_type, field="acquisition_type")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def run_hash(run: Any) -> str:
    """The hash of a run folder ``<experiment>_<hash6>``: what tells this run's files from another's."""
    return _validate_hash(Path(run).name.rsplit("_", 1)[-1])


def free_name(folder: Any, stem: str, ending: str) -> Path:
    """``folder/<stem><ending>``, or ``<stem>_001<ending>``, ...: the first no earlier file took.

    What the interface writes about a capture -- its focus curve, the objects
    found in it -- is named after the capture's acquisition type and label. A
    position taken again keeps its label, so what is written about it takes
    the next free name, and what was said about the earlier capture stays.
    The captures themselves are the driver's to name: it never overwrites an
    earlier file (the controller's contract).
    """
    folder = Path(folder)
    candidate, number = stem, 0
    while (folder / f"{candidate}{ending}").exists():
        number += 1
        candidate = f"{stem}_{number:03d}"
    return folder / f"{candidate}{ending}"


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


def move_record_images(record: dict, acquisition: Any) -> dict:
    """File every file a capture saved in the run, unchanged, and update the record's paths.

    ``files`` is where the driver lists every file it saved, the name the
    ZMART Controller's contract fixes so the interface finds the pictures on
    any microscope. Every file a plane names must be one of them, so that the
    record can never disagree with itself about what was saved.

    The layout is the driver's. A driver given the *acquisition* folder saves
    straight into it, in folders of its own (the Leica keeps its stores in
    ``data``, its projections and its log beside it), so its files are
    already where they belong and stay there. A driver whose software saves
    in a place of its own has its files moved into *acquisition*, keeping the
    layout they have under their common folder.

    Every source and destination is checked before the first move. If a later
    move fails, the files already moved go back where they were, so one
    capture is never left half in staging and half in the run.
    """

    files = record.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError(
            "the acquisition listed no files: a driver must name every file it saved under 'files'"
        )
    sources = list(dict.fromkeys(Path(value) for value in files))
    named = [plane["path"] for plane in record.get("planes", [])]
    unlisted = [value for value in named if Path(value) not in sources]
    if unlisted:
        raise RuntimeError(f"the capture names {unlisted}, not among the files it saved")

    destination = Path(acquisition)
    if all(source.resolve().is_relative_to(destination.resolve()) for source in sources):
        saved_in = destination
    else:
        saved_in = Path(os.path.commonpath([source.parent for source in sources]))
    filed = [(source, destination / source.relative_to(saved_in)) for source in sources]
    targets = [target for _, target in filed]
    if len(targets) != len(set(targets)):
        raise RuntimeError("acquire returned different files with the same filename")
    for source, _ in filed:
        if not source.exists():
            raise FileNotFoundError(f"acquired file does not exist: {source}")
    moves = [(source, target) for source, target in filed if source.resolve() != target.resolve()]
    for _, target in moves:
        if target.exists():
            raise FileExistsError(f"refusing to replace an existing acquisition file: {target}")

    moved: list[tuple[Path, Path]] = []
    try:
        for source, target in moves:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moved.append((source, target))
    except Exception:
        for source, target in reversed(moved):
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        raise

    mapped = {source: str(target) for source, target in filed}
    record["files"] = [mapped[source] for source in sources]
    for plane in record.get("planes", []):
        plane["path"] = mapped[Path(plane["path"])]
    return record

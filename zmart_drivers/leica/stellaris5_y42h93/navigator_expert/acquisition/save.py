"""Persist acquired LAS X exports into the workflow layout.

Public workflow:

    acq = acquire(client, job)
    saved = save(client, acq, output_root, naming)

``save`` owns persistence only. Source collection lives in
``lasx_native_autosave``; OME checks live in ``ome``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from shared.output_layout import (
    Naming,
    acquisition_dir,
    build_image_name,
)

from ..orientation import Orientation
from . import files as _files
from . import materialize as _materialize
from .capture import AcquisitionResult
from .files import (
    DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S,
    DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    DEFAULT_FILE_STABILITY_TIMEOUT_S,
)
from .lasx_native_autosave import (
    collect_lasx_native_autosave,
    native_autosave_base_folder,
    native_autosave_enabled,
)
from .product import (
    ExportedAcquisition,
    PlaneIndex,
    SavedAcquisition,
)

log = logging.getLogger(__name__)


def save_source_root() -> Path:
    """Return the LAS X native AutoSave source root.

    Sources come from the native AutoSave base folder in the active
    LAS X StartUp configuration.
    """
    if not native_autosave_enabled():
        raise RuntimeError(
            "LAS X native AutoSave is not enabled in the active StartUp configuration."
        )
    return native_autosave_base_folder()


def save(
    client: Any,
    acq: AcquisitionResult,
    output_root: str | Path,
    naming: Naming,
    *,
    lineage: dict | None = None,
    state: dict | None = None,
    orientation: Orientation | None = None,
    fix_ome: bool = True,
    cleanup_source: bool = False,
    file_stability_timeout_s: int = DEFAULT_FILE_STABILITY_TIMEOUT_S,
    export_completion_timeout_s: float = DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    export_completion_poll_interval_s: float = (DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S),
) -> SavedAcquisition:
    """Persist the files produced for *acq* into *output_root*.

    LAS X native AutoSave produces a writer-agnostic
    ``ExportedAcquisition``. This function persists that product into the
    flat ZMART OME-TIFF layout (one 2-D plane per file, no sidecar XML).
    When *state* is provided, the machine/software state at export time is
    embedded in each plane's OME-XML. When *orientation* is a non-identity rig
    D4, each plane is reoriented losslessly to stage-aligned axes as it is
    written (default: no reorientation).
    """
    exported = collect_lasx_native_autosave(
        client,
        acq,
        file_stability_timeout_s=file_stability_timeout_s,
        export_completion_timeout=export_completion_timeout_s,
        export_completion_poll_interval=export_completion_poll_interval_s,
    )
    return _persist_export(
        exported,
        Path(output_root),
        naming,
        lineage=lineage,
        state=state,
        orientation=orientation,
        fix_ome=fix_ome,
        cleanup_source=cleanup_source,
    )


def _persist_export(
    exported: ExportedAcquisition,
    output_root: Path,
    naming: Naming,
    *,
    lineage: dict | None,
    state: dict | None = None,
    orientation: Orientation | None = None,
    fix_ome: bool,
    cleanup_source: bool,
) -> SavedAcquisition:
    """Shared persistence for stable exported source paths.

    Flat: each 2-D plane is written directly under
    ``acquisition_dir(output_root, acquisition_type)`` and its OME-XML is
    embedded (no sidecar companion). *state* is embedded per-plane.
    """
    if cleanup_source and not exported.cleanup_source_supported:
        raise RuntimeError(
            f"cleanup_source is not supported for "
            f"{exported.source_exporter}. Native AutoSave sources are "
            f"LAS X project containers; deleting them requires an "
            f"explicit project-level cleanup policy."
        )

    image_paths: dict[PlaneIndex, Path] = {}
    vendor_records = _persist_vendor_metadata(exported, output_root, naming)

    # One load + one write instead of a full read-modify-write per plane
    # (O(n^2) disk I/O on large grids). The finally still persists records
    # for planes materialized before a mid-save failure.
    summary_path = output_root / "summary.json"
    summary = _load_summary(summary_path)
    summary_dirty = False
    try:
        for pos in exported.positions:
            for idx, image_src in sorted(pos.planes.items()):
                # The flat image name carries only c and z; the source
                # timepoint (idx.t) still drives which page is materialized.
                plane_naming = replace(naming, c=idx.c, z=idx.z)
                image_dest = acquisition_dir(
                    output_root, plane_naming.acquisition_type
                ) / build_image_name(plane_naming)
                image_dest.parent.mkdir(parents=True, exist_ok=True)

                _materialize.save_image_source_atomic(
                    image_src,
                    image_dest,
                    metadata=exported.metadata,
                    index=idx,
                    fix_ome=fix_ome,
                    state=state,
                    orientation=orientation,
                )
                image_paths[idx] = image_dest

                record = {
                    "naming": _naming_to_dict(plane_naming),
                    "image_path": _rel_posix(image_dest, output_root),
                    "source": _rel_posix(image_src.path, exported.source_root),
                    "source_exporter": exported.source_exporter,
                    "canonical_metadata": True,
                    "vendor_metadata": vendor_records,
                    "physical_size_um": _physical_size_record(exported.metadata),
                    "channel": _channel_record(exported.metadata, idx.c),
                    "lineage": lineage,
                }
                _upsert_summary_record(summary, record)
                summary_dirty = True
    finally:
        if summary_dirty:
            _write_summary_atomic(summary_path, summary)

    if cleanup_source:
        for p in exported.source_files:
            try:
                p.unlink()
            except OSError as e:
                log.warning("cleanup_source failed for %s: %s", p, e)

    return SavedAcquisition(
        image_paths=image_paths,
        naming=naming,
    )


def _persist_vendor_metadata(
    exported: ExportedAcquisition,
    output_root: Path,
    naming: Naming,
) -> list[dict]:
    if not exported.vendor_metadata_sources:
        return []
    vendor_dir = (
        acquisition_dir(output_root, naming.acquisition_type)
        / "vendor"
        / _safe_component(exported.source_exporter)
    )
    vendor_dir.mkdir(parents=True, exist_ok=True)

    records = []
    used_names: set[str] = set()
    for i, source in enumerate(exported.vendor_metadata_sources):
        name = _unique_vendor_name(_safe_component(source.name), used_names, i)
        dest = vendor_dir / name
        _materialize.save_vendor_metadata_atomic(source, dest)
        records.append(
            {
                "path": _rel_posix(dest, output_root),
                "sha256": _sha256(dest),
                "source": (
                    _rel_posix(source.path, exported.source_root)
                    if source.path is not None
                    else None
                ),
            }
        )
    return records


def _write_summary_atomic(summary_path: Path, data: dict) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _materialize._with_tmp_suffix(summary_path)
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(summary_path))


def _load_summary(summary_path: Path) -> dict:
    """Existing summary content, or a fresh structure when absent/corrupt."""
    if summary_path.is_file():
        try:
            with summary_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            # An externally corrupted summary must not abort a save whose
            # images are already written; rebuild it from this save on.
            log.warning("summary.json unreadable, starting fresh (%s): %s", summary_path, e)
    return {"acquisitions": []}


def _upsert_summary_record(data: dict, record: dict) -> None:
    """Insert *record* into the in-memory summary, replacing by image_path."""
    acqs = data.setdefault("acquisitions", [])
    new_path = record.get("image_path")
    for i, existing in enumerate(acqs):
        if new_path is not None and existing.get("image_path") == new_path:
            acqs[i] = record
            break
    else:
        acqs.append(record)


def _rel_posix(p: Path, base: Path) -> str:
    return _files._relative_posix(p, base, fallback_to_str=True)


def _naming_to_dict(n: Naming) -> dict:
    return {
        "acquisition_type": n.acquisition_type,
        "hash6": n.hash6,
        "position_label": n.position_label,
        "c": n.c,
        "z": n.z,
    }


def _physical_size_record(metadata) -> dict:
    return {
        "x": metadata.physical_size_x_um,
        "y": metadata.physical_size_y_um,
        "z": metadata.physical_size_z_um,
        "unit": "um",
    }


def _channel_record(metadata, c: int) -> dict:
    channel = metadata.channel(c)
    return {
        "index": channel.index,
        "name": channel.name,
        "color": channel.color,
        "wavelength_nm": channel.wavelength_nm,
    }


def _safe_component(value: str) -> str:
    out = []
    for ch in value:
        if ch.isalnum() or ch in {".", "-", "_"}:
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out).strip("._")
    return cleaned or "metadata"


def _unique_vendor_name(name: str, used: set[str], index: int) -> str:
    if name not in used:
        used.add(name)
        return name
    path = Path(name)
    stem = path.stem or "metadata"
    suffix = path.suffix
    candidate = f"{stem}_{index:03d}{suffix}"
    while candidate in used:
        index += 1
        candidate = f"{stem}_{index:03d}{suffix}"
    used.add(candidate)
    return candidate


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

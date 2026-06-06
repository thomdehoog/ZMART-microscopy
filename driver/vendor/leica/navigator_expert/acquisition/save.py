"""Persist acquired LAS X exports into the workflow layout.

Public workflow:

    acq = acquire(client, job)
    saved = save(client, acq, output_root, naming)

``save`` owns persistence only. Exporter-specific source collection
lives in dedicated collector modules; OME checks live in ``ome``.
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
    acquisition_data_dir,
    acquisition_metadata_dir,
    build_image_name,
    build_xml_name,
)

from . import materialize as _materialize
from . import ome_canonical as _canonical
from .capture import AcquisitionResult
from .lasx_native_autosave import (
    collect_lasx_native_autosave,
    native_autosave_base_folder,
    native_autosave_enabled,
)
from .navigator_expert_export import (
    DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S,
    DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    DEFAULT_FILE_STABILITY_TIMEOUT_S,
    collect_navigator_expert_export,
    navigator_expert_media_path,
)
from .product import (
    ExportedAcquisition,
    PlaneIndex,
    PositionIndex,
    SavedAcquisition,
)

log = logging.getLogger(__name__)

_EXPORTERS = {
    "navigator_expert": collect_navigator_expert_export,
    "lasx_native_autosave": collect_lasx_native_autosave,
}


def active_save_exporter(exporter: str | None = None) -> str:
    """Return the explicit exporter or the active profile's save exporter."""
    if exporter is not None:
        return exporter
    from ..core import profiles

    return profiles.ACQUISITION.save_exporter


def save_source_root(exporter: str | None = None) -> Path:
    """Return the LAS X source root used by *exporter*.

    ``navigator_expert`` sources come from the Navigator Expert exporter
    media path. ``lasx_native_autosave`` sources come from the native
    AutoSave base folder in the active LAS X StartUp configuration.
    ``exporter=None`` means use ``core.profiles.ACQUISITION.save_exporter``.
    """
    exporter = active_save_exporter(exporter)
    _collector_for_exporter(exporter)
    if exporter == "navigator_expert":
        return navigator_expert_media_path()
    if exporter == "lasx_native_autosave":
        if not native_autosave_enabled():
            raise RuntimeError(
                "LAS X native AutoSave is not enabled in the active StartUp "
                "configuration."
            )
        return native_autosave_base_folder()
    raise AssertionError(f"Unhandled save exporter: {exporter!r}")


def save(
    client: Any,
    acq: AcquisitionResult,
    output_root: str | Path,
    naming: Naming,
    *,
    lineage: dict | None = None,
    fix_ome: bool = True,
    cleanup_source: bool = False,
    file_stability_timeout_s: int = DEFAULT_FILE_STABILITY_TIMEOUT_S,
    export_completion_timeout_s: float = DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    export_completion_poll_interval_s: float = (
        DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S
    ),
    exporter: str | None = None,
) -> SavedAcquisition:
    """Persist the files produced for *acq* into *output_root*.

    The chosen source exporter produces a writer-agnostic
    ``ExportedAcquisition``. This function persists that product into
    the flat SMART OME-TIFF/XML workflow layout. ``exporter=None`` means
    use ``core.profiles.ACQUISITION.save_exporter``.
    """
    exporter = active_save_exporter(exporter)
    collect = _collector_for_exporter(exporter)

    exported = collect(
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
        fix_ome=fix_ome,
        cleanup_source=cleanup_source,
    )


def _collector_for_exporter(exporter: str):
    try:
        return _EXPORTERS[exporter]
    except KeyError as e:
        available = ", ".join(sorted(_EXPORTERS))
        raise ValueError(
            f"Unknown LAS X save exporter '{exporter}'. "
            f"Available exporters: {available}"
        ) from e


def _persist_export(
    exported: ExportedAcquisition,
    output_root: Path,
    naming: Naming,
    *,
    lineage: dict | None,
    fix_ome: bool,
    cleanup_source: bool,
) -> SavedAcquisition:
    """Shared persistence for stable exported source paths."""
    if cleanup_source and not exported.cleanup_source_supported:
        raise RuntimeError(
            f"cleanup_source is not supported for "
            f"{exported.source_exporter}. Native AutoSave sources are "
            f"LAS X project containers; deleting them requires an "
            f"explicit project-level cleanup policy."
        )

    image_paths: dict[PlaneIndex, Path] = {}
    xml_paths: dict[PositionIndex, Path] = {}
    vendor_records = _persist_vendor_metadata(exported, output_root, naming)

    for pos in exported.positions:
        xml_naming = replace(naming, t=pos.t)
        xml_dest = (
            acquisition_metadata_dir(output_root, xml_naming.acquisition_type)
            / build_xml_name(xml_naming)
        )
        xml_dest.parent.mkdir(parents=True, exist_ok=True)

        plane_names = {
            idx: build_image_name(replace(naming, t=idx.t, z=idx.z, c=idx.c))
            for idx in sorted(pos.planes)
        }
        companion = _canonical.companion_xml(
            exported.metadata,
            image_name=xml_dest.name,
            plane_filenames=plane_names,
        )
        _materialize.save_xml_bytes_atomic(companion, xml_dest, fix_ome=fix_ome)
        xml_paths[PositionIndex(t=pos.t, v=naming.v)] = xml_dest

        for idx, image_src in sorted(pos.planes.items()):
            plane_naming = replace(
                naming,
                t=idx.t,
                z=idx.z,
                c=idx.c,
            )
            image_dest = (
                acquisition_data_dir(output_root, plane_naming.acquisition_type)
                / build_image_name(plane_naming)
            )
            image_dest.parent.mkdir(parents=True, exist_ok=True)

            _materialize.save_image_source_atomic(
                image_src,
                image_dest,
                metadata=exported.metadata,
                index=idx,
                fix_ome=fix_ome,
            )
            image_paths[idx] = image_dest

            record = {
                "naming": _naming_to_dict(plane_naming),
                "image_path": _rel_posix(image_dest, output_root),
                "xml_path": _rel_posix(xml_dest, output_root),
                "source": _rel_posix(image_src.path, exported.media_path),
                "source_exporter": exported.source_exporter,
                "canonical_metadata": True,
                "vendor_metadata": vendor_records,
                "physical_size_um": _physical_size_record(exported.metadata),
                "channel": _channel_record(exported.metadata, idx.c),
                "lineage": lineage,
            }
            _append_summary_atomic(output_root / "summary.json", record)

    if cleanup_source:
        for p in exported.source_files:
            try:
                p.unlink()
            except OSError as e:
                log.warning("cleanup_source failed for %s: %s", p, e)

    return SavedAcquisition(
        image_paths=image_paths,
        xml_paths=xml_paths,
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
        acquisition_metadata_dir(output_root, naming.acquisition_type)
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
        records.append({
            "path": _rel_posix(dest, output_root),
            "sha256": _sha256(dest),
            "source": (
                _rel_posix(source.path, exported.media_path)
                if source.path is not None else None
            ),
        })
    return records


def _write_summary_atomic(summary_path: Path, data: dict) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _with_tmp_suffix(summary_path)
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(summary_path))


def _append_summary_atomic(summary_path: Path, record: dict) -> None:
    """Upsert *record* into ``summary.json`` atomically."""
    if summary_path.is_file():
        with summary_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = {"acquisitions": []}
    acqs = data.setdefault("acquisitions", [])
    new_path = record.get("image_path")
    for i, existing in enumerate(acqs):
        if new_path is not None and existing.get("image_path") == new_path:
            acqs[i] = record
            break
    else:
        acqs.append(record)
    _write_summary_atomic(summary_path, data)


def _with_tmp_suffix(p: Path) -> Path:
    return p.with_name(p.name + ".tmp")


def _rel_posix(p: Path, base: Path) -> str:
    try:
        return str(p.relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _naming_to_dict(n: Naming) -> dict:
    return {
        "acquisition_type": n.acquisition_type,
        "hash6": n.hash6,
        "k": n.k,
        "m": n.m,
        "g": n.g,
        "p": n.p,
        "t": n.t,
        "v": n.v,
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

"""Persist acquired LAS X exports into the workflow layout.

Public workflow:

    acq = acquire(client, job)
    saved = save(client, acq, output_root, naming)

``save`` owns persistence only. Exporter-specific source collection
lives in dedicated collector modules; OME checks live in ``ome``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import materialize as _materialize
from .capture import AcquisitionResult
from .navigator_expert_export import (
    DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S,
    DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    DEFAULT_FILE_STABILITY_TIMEOUT_S,
    collect_navigator_expert_export,
)
from .lasx_native_autosave import collect_lasx_native_autosave
from .product import (
    ExportedAcquisition,
    PlaneIndex,
    PositionIndex,
    SavedAcquisition,
)
from shared.output_layout import (
    Naming,
    acquisition_data_dir,
    acquisition_metadata_dir,
    build_image_name,
    build_xml_name,
)

log = logging.getLogger(__name__)

_EXPORTERS = {
    "navigator_expert": collect_navigator_expert_export,
    "lasx_native_autosave": collect_lasx_native_autosave,
}


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
    exporter: str = "navigator_expert",
) -> SavedAcquisition:
    """Persist the files produced for *acq* into *output_root*.

    The chosen source exporter produces a writer-agnostic
    ``ExportedAcquisition``. This function persists that product into
    the flat OME-TIFF/XML workflow layout. Known Leica OME metadata
    violations are repaired by default before persistence.
    """
    try:
        collect = _EXPORTERS[exporter]
    except KeyError as e:
        available = ", ".join(sorted(_EXPORTERS))
        raise ValueError(
            f"Unknown LAS X save exporter '{exporter}'. "
            f"Available exporters: {available}"
        ) from e

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

    for pos in exported.positions:
        xml_naming = replace(naming, t=pos.t)
        xml_dest = (
            acquisition_metadata_dir(output_root, xml_naming.acquisition_type)
            / build_xml_name(xml_naming)
        )
        xml_dest.parent.mkdir(parents=True, exist_ok=True)
        _materialize.save_xml_source_atomic(pos.xml, xml_dest, fix_ome=fix_ome)
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
                fix_ome=fix_ome,
            )
            image_paths[idx] = image_dest

            record = {
                "naming": _naming_to_dict(plane_naming),
                "image_path": _rel_posix(image_dest, output_root),
                "xml_path": _rel_posix(xml_dest, output_root),
                "source": _rel_posix(image_src.path, exported.media_path),
                "source_exporter": exported.source_exporter,
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

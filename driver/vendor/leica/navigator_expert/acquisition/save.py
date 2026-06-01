"""Persist acquired Navigator Expert exports into the workflow layout.

Public workflow:

    acq = acquire(client, job)
    saved = save(client, acq, output_root, naming)

``save`` owns persistence only. The exporter-specific source collection
lives in ``navigator_expert_export``; OME checks live in ``ome``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import ome as _ome
from .capture import AcquisitionResult
from .navigator_expert_export import (
    DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S,
    DEFAULT_EXPORT_COMPLETION_TIMEOUT_S,
    DEFAULT_FILE_STABILITY_TIMEOUT_S,
    collect_navigator_expert_export,
)
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
) -> SavedAcquisition:
    """Persist the files produced for *acq* into *output_root*.

    Current source workflow: ``navigator_expert_exporter``. Navigator
    Expert produces the files; the driver collects stable source paths
    and persists image/XML into the workflow layout. Known Leica OME
    metadata violations are repaired by default before persistence.
    """
    exported = collect_navigator_expert_export(
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
    image_paths: dict[PlaneIndex, Path] = {}
    xml_paths: dict[PositionIndex, Path] = {}

    for pos in exported.positions:
        xml_naming = replace(naming, t=pos.t)
        xml_dest = (
            acquisition_metadata_dir(output_root, xml_naming.acquisition_type)
            / build_xml_name(xml_naming)
        )
        xml_dest.parent.mkdir(parents=True, exist_ok=True)
        _save_xml_atomic(pos.xml_path, xml_dest, fix_ome=fix_ome)
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

            _save_image_atomic(
                image_src,
                image_dest,
                fix_ome=fix_ome,
            )
            image_paths[idx] = image_dest

            record = {
                "naming": _naming_to_dict(plane_naming),
                "image_path": _rel_posix(image_dest, output_root),
                "xml_path": _rel_posix(xml_dest, output_root),
                "source": _rel_posix(image_src, exported.media_path),
                "source_exporter": "navigator_expert_exporter",
                "lineage": lineage,
            }
            _append_summary_atomic(output_root / "summary.json", record)

    if cleanup_source:
        for p in list(exported.image_files) + list(exported.xml_files):
            try:
                p.unlink()
            except OSError as e:
                log.warning("cleanup_source failed for %s: %s", p, e)

    return SavedAcquisition(
        image_paths=image_paths,
        xml_paths=xml_paths,
        naming=naming,
    )

def _ome_ok(result: dict) -> bool:
    """check_ome_tiff / check_ome_xml_file success criterion."""
    return result["corrupted"] is False and result["error"] is None


def _validate_ome(image_path: Path, xml_path: Path, *, fix_ome: bool) -> None:
    """Check OME-TIFF and companion XML; optionally repair in place."""
    _validate_tiff(image_path, fix_ome=fix_ome)
    _validate_xml(xml_path, fix_ome=fix_ome)


def _validate_tiff(image_path: Path, *, fix_ome: bool) -> None:
    """Check OME-TIFF; optionally repair in place."""
    img_check = _ome.check_ome_tiff(image_path)
    if not _ome_ok(img_check):
        if fix_ome:
            _ome.fix_ome_tiff(image_path)
            img_check = _ome.check_ome_tiff(image_path)
        if not _ome_ok(img_check):
            raise RuntimeError(
                f"OME-TIFF validation failed: {image_path} :: {img_check}"
            )


def _validate_xml(xml_path: Path, *, fix_ome: bool) -> None:
    """Check companion OME-XML; optionally repair in place."""
    xml_check = _ome.check_ome_xml_file(xml_path)
    if not _ome_ok(xml_check):
        if fix_ome:
            _ome.fix_ome_xml_file(xml_path)
            xml_check = _ome.check_ome_xml_file(xml_path)
        if not _ome_ok(xml_check):
            raise RuntimeError(
                f"OME-XML validation failed: {xml_path} :: {xml_check}"
            )


def _save_image_atomic(
    image_src: Path,
    image_dest: Path,
    *,
    fix_ome: bool = False,
) -> None:
    """Atomic copy of one image plane to its canonical destination."""
    image_tmp = _with_tmp_suffix(image_dest)

    try:
        shutil.copy2(str(image_src), str(image_tmp))
        image_src_size = image_src.stat().st_size
        image_tmp_size = image_tmp.stat().st_size
        if image_tmp_size != image_src_size:
            raise RuntimeError(
                f"Image copy size mismatch: {image_tmp_size} != "
                f"{image_src_size} (source: {image_src})"
            )
        _validate_tiff(image_tmp, fix_ome=fix_ome)
    except BaseException:
        try:
            image_tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    os.replace(str(image_tmp), str(image_dest))


def _save_xml_atomic(
    xml_src: Path,
    xml_dest: Path,
    *,
    fix_ome: bool = False,
) -> None:
    """Atomic copy of one companion XML to its canonical destination."""
    xml_tmp = _with_tmp_suffix(xml_dest)

    try:
        shutil.copy2(str(xml_src), str(xml_tmp))
        xml_src_size = xml_src.stat().st_size
        xml_tmp_size = xml_tmp.stat().st_size
        if xml_tmp_size != xml_src_size:
            raise RuntimeError(
                f"XML copy size mismatch: {xml_tmp_size} != "
                f"{xml_src_size} (source: {xml_src})"
            )
        _validate_xml(xml_tmp, fix_ome=fix_ome)
    except BaseException:
        try:
            xml_tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    os.replace(str(xml_tmp), str(xml_dest))


def _save_atomic(
    image_src: Path,
    image_dest: Path,
    xml_src: Path,
    xml_dest: Path,
    *,
    fix_ome: bool = False,
) -> None:
    """All-or-nothing copy of image + XML pair to canonical destinations."""
    image_tmp = _with_tmp_suffix(image_dest)
    xml_tmp = _with_tmp_suffix(xml_dest)

    try:
        shutil.copy2(str(image_src), str(image_tmp))
        shutil.copy2(str(xml_src), str(xml_tmp))

        image_src_size = image_src.stat().st_size
        image_tmp_size = image_tmp.stat().st_size
        if image_tmp_size != image_src_size:
            raise RuntimeError(
                f"Image copy size mismatch: {image_tmp_size} != "
                f"{image_src_size} (source: {image_src})"
            )
        xml_src_size = xml_src.stat().st_size
        xml_tmp_size = xml_tmp.stat().st_size
        if xml_tmp_size != xml_src_size:
            raise RuntimeError(
                f"XML copy size mismatch: {xml_tmp_size} != "
                f"{xml_src_size} (source: {xml_src})"
            )
        _validate_ome(image_tmp, xml_tmp, fix_ome=fix_ome)
    except BaseException:
        for tmp in (image_tmp, xml_tmp):
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    os.replace(str(image_tmp), str(image_dest))
    try:
        os.replace(str(xml_tmp), str(xml_dest))
    except BaseException:
        log.error(
            "PARTIAL SAVE: image landed at %s but XML failed to replace "
            "from %s -> %s. Atomic-unit contract violated; investigate "
            "filesystem health.", image_dest, xml_tmp, xml_dest,
        )
        raise


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

"""Materialize exported acquisition sources into canonical files.

Collectors describe where pixels and metadata came from. This module
contains the generic source-ref -> destination-file mechanics used by
the current flat OME-TIFF/XML writer.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import ome as _ome
from .product import PlaneSource, XmlSource


def save_image_source_atomic(
    image_src: PlaneSource,
    image_dest: Path,
    *,
    fix_ome: bool = False,
) -> None:
    """Materialize one image source to a canonical single-plane file."""
    if image_src.page_index is None:
        _save_image_atomic(image_src.path, image_dest, fix_ome=fix_ome)
        return
    _save_tiff_page_atomic(image_src, image_dest, fix_ome=fix_ome)


def save_xml_source_atomic(
    xml_src: XmlSource,
    xml_dest: Path,
    *,
    fix_ome: bool = False,
) -> None:
    """Materialize one XML source to a canonical companion XML."""
    if xml_src.embedded:
        _save_embedded_xml_atomic(xml_src.path, xml_dest, fix_ome=fix_ome)
        return
    _save_xml_atomic(xml_src.path, xml_dest, fix_ome=fix_ome)


def ome_ok(result: dict) -> bool:
    """check_ome_tiff / check_ome_xml_file success criterion."""
    return result["corrupted"] is False and result["error"] is None


def _validate_tiff(image_path: Path, *, fix_ome: bool) -> None:
    """Check OME-TIFF; optionally repair in place."""
    img_check = _ome.check_ome_tiff(image_path)
    if not ome_ok(img_check):
        if fix_ome:
            _ome.fix_ome_tiff(image_path)
            img_check = _ome.check_ome_tiff(image_path)
        if not ome_ok(img_check):
            raise RuntimeError(
                f"OME-TIFF validation failed: {image_path} :: {img_check}"
            )


def _validate_xml(xml_path: Path, *, fix_ome: bool) -> None:
    """Check companion OME-XML; optionally repair in place."""
    xml_check = _ome.check_ome_xml_file(xml_path)
    if not ome_ok(xml_check):
        if fix_ome:
            _ome.fix_ome_xml_file(xml_path)
            xml_check = _ome.check_ome_xml_file(xml_path)
        if not ome_ok(xml_check):
            raise RuntimeError(
                f"OME-XML validation failed: {xml_path} :: {xml_check}"
            )


def _save_image_atomic(
    image_src: Path,
    image_dest: Path,
    *,
    fix_ome: bool = False,
) -> None:
    """Atomic copy of one single-plane image to its canonical destination."""
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


def _save_tiff_page_atomic(
    image_src: PlaneSource,
    image_dest: Path,
    *,
    fix_ome: bool = False,
) -> None:
    """Atomic extraction of one TIFF page to a canonical OME-TIFF."""
    if image_src.page_index is None:
        raise ValueError("page_index is required for TIFF-page materialization")

    image_tmp = _with_tmp_suffix(image_dest)
    try:
        import tifffile

        with tifffile.TiffFile(str(image_src.path)) as tif:
            if image_src.page_index < 0 or image_src.page_index >= len(tif.pages):
                raise RuntimeError(
                    f"TIFF page index {image_src.page_index} out of range "
                    f"for {image_src.path}"
                )
            arr = tif.pages[image_src.page_index].asarray()
        if arr.ndim != 2:
            raise RuntimeError(
                f"Expected a single 2-D image plane, got shape {arr.shape} "
                f"from {image_src.path} page {image_src.page_index}"
            )
        tifffile.imwrite(
            str(image_tmp),
            arr,
            ome=True,
            metadata={"axes": "YX"},
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


def _save_embedded_xml_atomic(
    tiff_src: Path,
    xml_dest: Path,
    *,
    fix_ome: bool = False,
) -> None:
    """Extract TIFF tag-270 OME-XML to a canonical companion XML."""
    xml_tmp = _with_tmp_suffix(xml_dest)

    try:
        xml_tmp.write_bytes(extract_embedded_ome_xml(tiff_src))
        _validate_xml(xml_tmp, fix_ome=fix_ome)
    except BaseException:
        try:
            xml_tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    os.replace(str(xml_tmp), str(xml_dest))


def extract_embedded_ome_xml(tiff_src: Path) -> bytes:
    """Return raw OME-XML from TIFF ImageDescription tag 270."""
    try:
        data = tiff_src.read_bytes()
    except OSError as e:
        raise RuntimeError(f"Could not read embedded OME source {tiff_src}: {e}")

    xml_raw, _offset, _count, _entry_pos, endian_or_err = _ome._read_tiff_tag_270(
        data
    )
    if xml_raw is not None:
        return xml_raw

    try:
        import tifffile

        with tifffile.TiffFile(str(tiff_src)) as tif:
            description = tif.pages[0].description
    except Exception as e:
        raise RuntimeError(
            f"Could not extract embedded OME-XML from {tiff_src}: "
            f"{endian_or_err}; tifffile fallback failed: {e}"
        ) from e
    if not description or "<OME" not in description:
        raise RuntimeError(
            f"Could not extract embedded OME-XML from {tiff_src}: "
            f"{endian_or_err}; tifffile found no OME ImageDescription"
        )
    return description.encode("utf-8")


def _with_tmp_suffix(p: Path) -> Path:
    return p.with_name(p.name + ".tmp")

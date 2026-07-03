"""Materialize exported sources into canonical SMART OME files."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import ome as _ome
from . import ome_canonical as _canonical
from .product import AcquisitionMetadata, PlaneIndex, PlaneSource, VendorMetadataSource


def save_image_source_atomic(
    image_src: PlaneSource,
    image_dest: Path,
    *,
    metadata: AcquisitionMetadata,
    index: PlaneIndex,
    fix_ome: bool = False,
) -> None:
    """Read one source plane and write a canonical SMART OME-TIFF."""
    image_tmp = _with_tmp_suffix(image_dest)
    try:
        import tifffile

        arr = _read_source_plane(image_src)
        if arr.ndim != 2:
            raise RuntimeError(
                f"Expected a single 2-D image plane, got shape {arr.shape} from {image_src.path}"
            )
        xml = _canonical.plane_xml(
            metadata,
            index=index,
            filename=image_dest.name,
            shape_yx=(int(arr.shape[0]), int(arr.shape[1])),
        )
        tifffile.imwrite(str(image_tmp), arr, description=xml.decode("utf-8"))
        _validate_tiff(image_tmp, fix_ome=fix_ome)
    except BaseException:
        try:
            image_tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    os.replace(str(image_tmp), str(image_dest))


def save_xml_bytes_atomic(xml_bytes: bytes, xml_dest: Path, *, fix_ome: bool = False) -> None:
    """Write canonical companion OME-XML atomically."""
    xml_tmp = _with_tmp_suffix(xml_dest)
    try:
        xml_tmp.write_bytes(xml_bytes)
        _validate_xml(xml_tmp, fix_ome=fix_ome)
    except BaseException:
        try:
            xml_tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    os.replace(str(xml_tmp), str(xml_dest))


def save_vendor_metadata_atomic(source: VendorMetadataSource, dest: Path) -> None:
    """Persist raw vendor metadata as provenance, not output truth."""
    tmp = _with_tmp_suffix(dest)
    try:
        if source.data is not None:
            tmp.write_bytes(source.data)
        elif source.path is not None:
            shutil.copy2(str(source.path), str(tmp))
        else:
            raise RuntimeError(f"vendor metadata source has no data/path: {source}")
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    os.replace(str(tmp), str(dest))


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
            raise RuntimeError(f"OME-TIFF validation failed: {image_path} :: {img_check}")


def _validate_xml(xml_path: Path, *, fix_ome: bool) -> None:
    """Check companion OME-XML; optionally repair in place."""
    xml_check = _ome.check_ome_xml_file(xml_path)
    if not ome_ok(xml_check):
        if fix_ome:
            _ome.fix_ome_xml_file(xml_path)
            xml_check = _ome.check_ome_xml_file(xml_path)
        if not ome_ok(xml_check):
            raise RuntimeError(f"OME-XML validation failed: {xml_path} :: {xml_check}")


def _read_source_plane(image_src: PlaneSource):
    import tifffile

    if image_src.page_index is None:
        return tifffile.imread(str(image_src.path))
    with tifffile.TiffFile(str(image_src.path)) as tif:
        if image_src.page_index < 0 or image_src.page_index >= len(tif.pages):
            raise RuntimeError(
                f"TIFF page index {image_src.page_index} out of range for {image_src.path}"
            )
        return tif.pages[image_src.page_index].asarray()


def _with_tmp_suffix(p: Path) -> Path:
    return p.with_name(p.name + ".tmp")

"""Materialize exported sources into canonical ZMART OME files."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import replace
from pathlib import Path

from ..orientation import Orientation, reorient_array
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
    state: dict | None = None,
    orientation: Orientation | None = None,
) -> None:
    """Read one source plane and write a canonical ZMART OME-TIFF.

    When *state* is provided, the machine/software state at export time is
    embedded in the plane's OME-XML (no sidecar). When *orientation* is a
    non-identity rig D4, the plane pixels are reoriented losslessly to
    stage-aligned axes before the OME is generated, so the written file is
    self-consistent (a 90/270 swaps SizeX/SizeY via the rotated shape and
    swaps PhysicalSizeX/Y via the metadata below).
    """
    image_tmp = _with_tmp_suffix(image_dest)
    try:
        import tifffile

        arr = _read_source_plane(image_src)
        if arr.ndim != 2:
            raise RuntimeError(
                f"Expected a single 2-D image plane, got shape {arr.shape} from {image_src.path}"
            )
        if orientation is not None and not orientation.is_identity:
            arr = reorient_array(arr, orientation)
            if orientation.swaps_axes:
                # 90/270 transposes the grid: SizeX/SizeY follow the rotated
                # shape_yx below; swap the physical pixel sizes to match.
                metadata = replace(
                    metadata,
                    physical_size_x_um=metadata.physical_size_y_um,
                    physical_size_y_um=metadata.physical_size_x_um,
                )
        xml = _canonical.plane_xml(
            metadata,
            index=index,
            filename=image_dest.name,
            shape_yx=(int(arr.shape[0]), int(arr.shape[1])),
            state=state,
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


def extract_embedded_ome_xml(tiff_src: Path) -> bytes:
    return _canonical.extract_embedded_ome_xml(tiff_src)


def _with_tmp_suffix(p: Path) -> Path:
    # PID + random suffix: a fixed '.tmp' would let two writers of the same
    # destination clobber each other's temp file before os.replace.
    return p.with_name(f"{p.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")

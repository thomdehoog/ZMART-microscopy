"""Controller-only simulation hijack (workflow.hijack_records).

Exercises the entry point the v4 notebook uses: given the records
``run_overview`` / ``acquire_targets`` return (each with ``"images"`` paths),
overwrite each saved plane's pixels with mock content -- gated per-frame on the
positive ``SystemTypeName == "SIMULATOR"`` allowlist, deriving the acquisition
dir from the file's own parent and the ``Naming`` from its filename.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile
from workflow import NonSimulatorFrameError, get_provider, hijack_records

from shared.output_layout.naming import Naming, build_image_name

_OME_DESC = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
    '<Image ID="Image:0"><Pixels ID="Pixels:0" DimensionOrder="XYCZT" '
    'Type="uint16" SizeX="16" SizeY="16" SizeC="1" SizeZ="1" SizeT="1"/></Image>'
    '<OriginalMetadata Name="Data - Image - Attachment - SystemTypeName" '
    'Value="SIMULATOR"/>'
    "</OME>"
)


def _write_vendor_system_type(acq_dir: Path, system_type: str, *, name="metadata_A.xlif") -> None:
    vendor_dir = acq_dir / "vendor" / "lasx_native_autosave"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    (vendor_dir / name).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Metadata>"
        f'<Attachment Name="HardwareSetting" SystemTypeName="{system_type}">'
        '<ATLConfocalSettingDefinition SystemSerialNumber="TEST" />'
        "</Attachment></Metadata>",
        encoding="utf-8",
    )


def _saved_plane(
    tmp_path: Path,
    *,
    acquisition_type="overview",
    position_label="g00000-p00001",
    system_type: str | None = "SIMULATOR",
    fill: int = 100,
    shape=(16, 16),
) -> Path:
    """Write one flat canonical plane inside its acquisition dir + vendor XLIF.

    Returns the image path. ``hijack_records`` derives the acquisition dir as
    the image's own parent, so the plane must live *inside* it.
    """
    acq_dir = tmp_path / acquisition_type
    acq_dir.mkdir(parents=True, exist_ok=True)
    if system_type is not None:
        _write_vendor_system_type(acq_dir, system_type)
    naming = Naming(
        acquisition_type=acquisition_type, hash6="abcdef", position_label=position_label
    )
    path = acq_dir / build_image_name(naming)
    arr = np.full(shape, fill, dtype=np.uint16)
    tifffile.imwrite(path, arr, description=_OME_DESC, ome=False, photometric="minisblack")
    return path


def _constant_provider(value: int):
    def _p(shape, dtype, *, naming):
        return np.full(shape, value, dtype=dtype)

    return _p


def test_hijack_records_overwrites_simulator_plane(tmp_path):
    img = _saved_plane(tmp_path)
    assert tifffile.imread(img).max() == 100

    n = hijack_records([{"images": [str(img)]}], _constant_provider(42))

    assert n == 1
    out = tifffile.imread(img)
    assert out.min() == 42 and out.max() == 42


def test_hijack_records_preserves_ome_description(tmp_path):
    img = _saved_plane(tmp_path)
    with tifffile.TiffFile(img) as tif:
        before = tif.pages[0].description

    hijack_records([{"images": [str(img)]}], _constant_provider(7))

    with tifffile.TiffFile(img) as tif:
        after = tif.pages[0].description
    assert after == before
    assert 'Value="SIMULATOR"' in after


def test_hijack_records_counts_all_planes_across_records(tmp_path):
    a = _saved_plane(tmp_path / "run0", position_label="g00000-p00000")
    b = _saved_plane(tmp_path / "run1", position_label="g00000-p00001")
    records = [{"images": [str(a)]}, {"images": [str(b)]}]

    assert hijack_records(records, _constant_provider(9)) == 2
    assert tifffile.imread(a).max() == 9
    assert tifffile.imread(b).max() == 9


def test_hijack_records_rejects_non_simulator_and_leaves_bytes(tmp_path):
    img = _saved_plane(tmp_path, system_type="STELLARIS 8")
    original = img.read_bytes()

    with pytest.raises(NonSimulatorFrameError):
        hijack_records([{"images": [str(img)]}], _constant_provider(42))

    assert img.read_bytes() == original


def test_hijack_records_rejects_missing_vendor_metadata(tmp_path):
    img = _saved_plane(tmp_path, system_type=None)  # no vendor XLIF at all
    original = img.read_bytes()

    with pytest.raises(NonSimulatorFrameError):
        hijack_records([{"images": [str(img)]}], _constant_provider(42))

    assert img.read_bytes() == original


def test_hijack_records_with_real_mitosis_provider(tmp_path):
    """End-to-end with the actual overview provider: content changes, shape and
    OME envelope preserved (so cellpose downstream sees realistic cells)."""
    pytest.importorskip("skimage")
    img = _saved_plane(tmp_path, position_label="g00000-p00003")
    before = tifffile.imread(img)

    hijack_records([{"images": [str(img)]}], get_provider("skimage_human_mitosis"))

    after = tifffile.imread(img)
    assert after.shape == before.shape
    assert after.dtype == before.dtype
    assert not np.array_equal(after, before)  # real mock content, not the flat fill
    with tifffile.TiffFile(img) as tif:
        assert 'Value="SIMULATOR"' in tif.pages[0].description


def test_hijack_records_empty_is_noop(tmp_path):
    assert hijack_records([], _constant_provider(1)) == 0
    assert hijack_records([{"images": []}], _constant_provider(1)) == 0

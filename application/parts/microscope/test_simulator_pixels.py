from pathlib import Path

import numpy as np
import pytest
import zarr

from application.parts.microscope.simulator_pixels import SimulatorPixels
from application.parts.storage.test_zarr_positions import a_z_stack
from application.parts.storage.zarr_positions import position_store_from_record


@pytest.mark.parametrize("heights", [(-4, 0, 4), (4, 0, -4)])
def test_saved_planes_stay_unchanged_and_pixels_follow_specimen_z(tmp_path, heights):
    record = a_z_stack(tmp_path, heights=heights)
    vendor = tmp_path / "vendor.xlif"
    vendor.write_text('<Image SystemTypeName="SIMULATOR"/>')
    record["vendor_metadata"] = [vendor]
    for plane in record["planes"]:
        plane.update(x_um=32, y_um=32)
    original = {p["path"]: Path(p["path"]).read_bytes() for p in record["planes"]}
    store = position_store_from_record(
        record, tmp_path / "positions", pixel_provider=SimulatorPixels()
    )
    group = zarr.open_group(str(store), mode="r")
    # World cell at (32, 32) is at physical Z=-4, regardless of vendor index.
    assert group["0"][0, 0, 0, 32, 32] == 20000
    assert group["0"][0, 0, 1, 32, 32] == 0
    assert group["0"][0, 0, 2, 32, 32] == 0
    assert group["0"][0, 0, 0, 0, 0] == 0
    assert group.attrs["zmart_microscopy"]["synthetic_pixels"]["synthetic"] is True
    assert all(Path(p).read_bytes() == data for p, data in original.items())


@pytest.mark.parametrize("identity", [None, "STELLARIS", "SIMULATOR"])
def test_identity_and_missing_files_do_not_become_synthetic_success(tmp_path, identity):
    record = a_z_stack(tmp_path)
    if identity:
        vendor = tmp_path / "vendor.xlif"
        vendor.write_text(f'<Image SystemTypeName="{identity}"/>')
        record["vendor_metadata"] = [vendor]
    record["planes"][0]["path"] = str(tmp_path / "missing.tif")
    with pytest.raises((RuntimeError, FileNotFoundError)):
        position_store_from_record(record, tmp_path / "positions", pixel_provider=SimulatorPixels())
    assert not (tmp_path / "positions").exists()


def test_missing_coordinates_refused_and_overlapping_fields_agree():
    provider = SimulatorPixels()
    plane = dict(x_um=32, y_um=32, z_um=-4, t=1, c=2)
    left = provider((64, 64), np.uint16, plane=plane, pixel_um=(1, 1))
    right = provider((64, 64), np.uint16, plane={**plane, "x_um": 64}, pixel_um=(1, 1))
    np.testing.assert_array_equal(left[:, 32:], right[:, :32])
    with pytest.raises(ValueError, match="recorded"):
        provider((64, 64), np.uint16, plane={**plane, "z_um": None}, pixel_um=(1, 1))


@pytest.mark.parametrize("duplicate", [False, True])
def test_incomplete_or_duplicate_slots_are_not_published_as_acquired_black(tmp_path, duplicate):
    record = a_z_stack(tmp_path, heights=(0, 1))
    if duplicate:
        record["planes"].append(dict(record["planes"][0]))
    else:
        record["planes"].append({**record["planes"][0], "c": 1})
    with pytest.raises(ValueError, match="one saved plane per T/C/Z"):
        position_store_from_record(record, tmp_path / "positions")
    assert not (tmp_path / "positions").exists()

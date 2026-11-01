import numpy as np
import pytest
import tifffile

from ..storage.test_zarr_positions import a_z_stack
from ..storage.zarr_positions import position_store_from_record
from . import detection
from .workflows import step_module

read_images = step_module("object_analysis", "read_images")
segment_watershed = step_module("object_analysis", "segment_watershed")


def segmented(path, z):
    """The position through read_images and segment_watershed: the detection, and the image read."""
    given = {"image_path": path, "channels": [0], "z_selection": z}
    data = read_images.run({"input": given, "metadata": {"verbose": 0}}, {})
    found = segment_watershed.run(data, {}, threshold=100, diameter=14)["segment_watershed"]
    return {**found, "image": data["read_images"]["image"]}


def test_capture_channels_match_first_timepoint_reader(tmp_path):
    record = a_z_stack(tmp_path, heights=(0,), acquisition_type="overview")
    plane = record["planes"][0]
    record["planes"] = [{**plane, "t": t, "c": c} for t in (4, 5) for c in (2, 7)]
    record["zarr"] = str(position_store_from_record(record, tmp_path / "positions"))
    given = detection.what_was_captured(record, field=0, settings={})
    assert given["channels"] == [0]
    assert given["extra_channel_indices"] == [1]


@pytest.mark.parametrize("depth", [5, 21])
def test_real_detector_sees_objects_outside_middle_plane(tmp_path, depth):
    record = a_z_stack(tmp_path, heights=tuple(reversed(range(depth))), acquisition_type="overview")
    yy, xx = np.mgrid[:64, :64]
    for i, plane in enumerate(record["planes"]):
        image = np.zeros((64, 64), np.uint16)
        if i == 0:
            image[(xx - 20) ** 2 + (yy - 20) ** 2 < 7**2] = 10000
        if i == depth - 1:
            image[(xx - 44) ** 2 + (yy - 44) ** 2 < 7**2] = 20000
        tifffile.imwrite(plane["path"], image)
    record["zarr"] = str(position_store_from_record(record, tmp_path / "positions"))
    given = detection.what_was_captured(
        record,
        field=0,
        settings={"method": "fast", "threshold": 100, "diameter": 14, "border": 2},
    )
    assert given["z_selection"] == "max"
    assert "tile_z_um" not in given
    assert given["diameter"] == 14  # the store's 1 um/px
    assert given["border_margin_px"] == 2
    old = segmented(record["zarr"], "mid")
    result = segmented(record["zarr"], given["z_selection"])
    assert old["n_objects"] == 0
    assert result["masks"][20, 20] > 0
    assert result["masks"][44, 44] > 0
    # The image the detector read: the one channel asked for, as a plane.
    read = np.asarray(result["image"])
    read = read if read.ndim == 2 else read[..., 0]
    assert read[20, 20] == 10000
    assert read[44, 44] == 20000
    # Rerunning the same position path must consume its rewritten stack.
    for i, plane in enumerate(record["planes"]):
        image = np.zeros((64, 64), np.uint16)
        if i == 0:
            image[(xx - 32) ** 2 + (yy - 32) ** 2 < 7**2] = 15000
        tifffile.imwrite(plane["path"], image)
    assert str(position_store_from_record(record, tmp_path / "positions")) == record["zarr"]
    rewritten = segmented(record["zarr"], "max")
    assert rewritten["masks"][32, 32] > 0
    assert rewritten["masks"][20, 20] == rewritten["masks"][44, 44] == 0

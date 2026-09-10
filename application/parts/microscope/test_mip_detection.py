import numpy as np
import pytest
import tifffile

from application.parts.microscope import detection
from application.parts.storage.test_zarr_positions import a_z_stack
from application.parts.storage.zarr_positions import position_store_from_record
from zmart_analysis.workflows.object_analysis.steps import detect_objects


def test_capture_channels_match_first_timepoint_reader(tmp_path):
    record = a_z_stack(tmp_path, heights=(0,), acquisition_type="overview")
    plane = record["planes"][0]
    record["planes"] = [{**plane, "t": t, "c": c} for t in (4, 5) for c in (2, 7)]
    record["zarr"] = "completed.ome.zarr"
    given = detection.what_was_captured(record, field=0, pixel_um=1, settings={})
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
        pixel_um=0.1,
        settings={"method": "fast", "threshold": 100, "diameter": 14, "border": 2},
    )
    assert given["z_selection"] == "max"
    assert given["tile_z_um"] is None
    assert given["diameter"] == 14  # stored 1 um/px, not the instrument-now 0.1
    assert given["border_margin_px"] == 2
    args = dict(method="fast", channels=[0], threshold=100, diameter=14, gpu=False)
    old = detect_objects.segment_position(record["zarr"], {}, z="mid", **args)
    result = detect_objects.segment_position(record["zarr"], {}, z=given["z_selection"], **args)
    assert old["n_objects"] == 0
    assert result["masks"][20, 20] > 0
    assert result["masks"][44, 44] > 0
    assert result["image_2d"][20, 20] == 10000
    assert result["image_2d"][44, 44] == 20000
    # Rerunning the same position path must consume its rewritten stack.
    for i, plane in enumerate(record["planes"]):
        image = np.zeros((64, 64), np.uint16)
        if i == 0:
            image[(xx - 32) ** 2 + (yy - 32) ** 2 < 7**2] = 15000
        tifffile.imwrite(plane["path"], image)
    assert str(position_store_from_record(record, tmp_path / "positions")) == record["zarr"]
    rewritten = detect_objects.segment_position(record["zarr"], {}, z="max", **args)
    assert rewritten["masks"][32, 32] > 0
    assert rewritten["masks"][20, 20] == rewritten["masks"][44, 44] == 0

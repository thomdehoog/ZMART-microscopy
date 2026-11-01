"""Canonical pixels and projection identity across consumers."""

import json
from types import SimpleNamespace

import numpy as np
import pytest
import zarr

from ..analysis import detection
from ..analysis.workflows import step_module
from ..bridge import pictures, state
from ..storage import jpeg_tiles
from ..storage.test_zarr_positions import a_z_stack
from ..storage.zarr_positions import position_store_from_record

read_images = step_module("object_analysis", "read_images")
segment_watershed = step_module("object_analysis", "segment_watershed")


def test_preview_uses_the_same_canonical_mip_as_detection(tmp_path, monkeypatch):
    record = a_z_stack(tmp_path, heights=(4, 0, -4), acquisition_type="overview")
    record["planes"] = [
        {**p, "c": c, "t": t} for p in record["planes"] for c in (2, 7) for t in (3, 4)
    ]
    record["zarr"] = str(position_store_from_record(record, tmp_path / "positions"))
    monkeypatch.setattr(state, "records", {"overview": [record]})
    monkeypatch.setattr(state, "displayed_pictures", {})
    monkeypatch.setattr(jpeg_tiles, "_as_jpeg", lambda pixels, quality: pixels)
    shown = pictures.a_picture_as_displayed(
        "overview",
        record["position_label"],
        [{"c": 0, "visible": True, "window": [0, 40000], "color": "#ff0000"}],
    )
    expected = read_images.load_plane(record["zarr"], t=0, c=0, z="max")[0]
    np.testing.assert_allclose(shown[..., 0], expected.astype("float32") / 40000 * 255)
    assert expected.max() > 0
    assert np.count_nonzero(shown[..., 1:]) == 0


def test_extra_channel_features_read_max_and_checkpoint_identifies_it(tmp_path):
    record = a_z_stack(tmp_path, heights=(0, 1, 2), acquisition_type="overview")
    record["planes"] += [{**p, "c": 1} for p in record["planes"]]
    record["zarr"] = str(position_store_from_record(record, tmp_path / "positions"))
    group = zarr.open_group(record["zarr"], mode="r+")
    array = group["0"]
    array[:] = 0
    array[0, 0, 0, 15:30, 15:30] = 10000
    array[0, 1, 0] = 700
    array[0, 1, 1] = 2
    array[0, 1, 2] = 900
    inp = {
        **detection.what_was_captured(record, field=0, settings={}),
        "image_path": record["zarr"],
        "channels": [0],
        "extra_channel_indices": [1],
        "z_selection": "max",
        "method": "fast",
        "threshold": 100,
        "diameter": 14,
        "gpu": False,
        "output_dir": str(tmp_path / "analysis"),
    }
    read = read_images.run({"input": inp, "metadata": {"verbose": 0}}, {})
    # The extra channel is read as a maximum projection too, for the features.
    np.testing.assert_array_equal(read["read_images"]["extra_channels"][0], 900)
    result = segment_watershed.run(read, {})
    assert result["segment_watershed"]["n_objects"] > 0
    checkpoint = json.loads(
        next((tmp_path / "analysis").rglob("detection_checkpoint.json")).read_text()
    )
    assert checkpoint["z_selection"] == "max"
    assert result["segment_watershed"]["segmentation_params"]["z_selection"] == "max"
    # The projection is part of the segmentation's identity
    middle = read_images.run({"input": {**inp, "z_selection": "mid"}, "metadata": {"verbose": 0}}, {})
    middle = segment_watershed.run(middle, {})["segment_watershed"]
    assert middle["segmentation_params_hash"] != result["segment_watershed"]["segmentation_params_hash"]


def test_target_area_and_radius_use_captured_calibration(tmp_path):
    record = a_z_stack(tmp_path, heights=(0,), acquisition_type="overview")
    record["zarr"] = str(position_store_from_record(record, tmp_path / "positions"))
    table = {
        "object_id": ["one"],
        "area": [100],
        "stage_x_um": [2],
        "stage_y_um": [3],
        "intensity_mean": [5],
        "label": [1],
    }
    analysis = SimpleNamespace(
        run=lambda *args: {"object_analysis": {"objects": {"properties": table}}}
    )
    result = detection.through(analysis)(record, 0, {})
    assert result["cells"][0]["area"] == 100
    assert result["cells"][0]["r"] == pytest.approx(np.sqrt(100 / np.pi))

"""Canonical pixels, projection identity and simulator refusal across consumers."""

import json
from types import SimpleNamespace

import numpy as np
import pytest
import zarr

from application.framework import bridge
from application.parts.microscope import detection
from application.parts.microscope.hijack import NonSimulatorFrameError
from application.parts.microscope.simulator_pixels import SimulatorPixels
from application.parts.storage import jpeg_tiles
from application.parts.storage.test_zarr_positions import a_z_stack
from application.parts.storage.zarr_positions import position_store_from_record
from zmart_analysis.workflows.object_analysis.steps import detect_objects


def test_simulator_refusal_propagates_out_of_ingestion(tmp_path, monkeypatch):
    record = a_z_stack(tmp_path)
    monkeypatch.setattr(bridge, "_run", tmp_path)
    monkeypatch.setattr(bridge, "_pixel_provider", SimulatorPixels())
    with pytest.raises(NonSimulatorFrameError):
        bridge._keep_position_as_zarr(record, "overview")
    assert not record.get("zarr")


def test_focus_stops_before_the_next_point_on_simulator_refusal(tmp_path):
    from application.parts.microscope.test_focus_run import _score, _StubSession, measure_focus

    session = _StubSession({(0, 0): 1, (10, 0): 2}, staging=tmp_path)

    def refuse(record):
        raise NonSimulatorFrameError("not a simulator")

    with pytest.raises(NonSimulatorFrameError):
        measure_focus(
            session,
            [{"x": 0, "y": 0}, {"x": 10, "y": 0}],
            score=_score,
            output_root=tmp_path / "run",
            keep=refuse,
        )
    assert len(session.captured) == 1


def test_preview_uses_the_same_canonical_mip_as_detection(tmp_path, monkeypatch):
    record = a_z_stack(tmp_path, heights=(4, 0, -4), acquisition_type="overview")
    vendor = tmp_path / "vendor.xlif"
    vendor.write_text('<Image SystemTypeName="SIMULATOR"/>')
    record["vendor_metadata"] = [vendor]
    for plane in record["planes"]:
        plane.update(x_um=32, y_um=32)
    record["planes"] = [
        {**p, "c": c, "t": t} for p in record["planes"] for c in (2, 7) for t in (3, 4)
    ]
    record["zarr"] = str(
        position_store_from_record(record, tmp_path / "positions", pixel_provider=SimulatorPixels())
    )
    monkeypatch.setattr(bridge, "_records", {"overview": [record]})
    monkeypatch.setattr(bridge, "_displayed_pictures", {})
    monkeypatch.setattr(jpeg_tiles, "_as_jpeg", lambda pixels, quality: pixels)
    shown = bridge._a_picture_as_displayed(
        "overview",
        record["position_label"],
        [{"c": 0, "visible": True, "window": [0, 40000], "color": "#ff0000"}],
    )
    expected = detect_objects.load_plane(record["zarr"], t=0, c=0, z="max")[0]
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
        **detection.what_was_captured(record, field=0, pixel_um=1, settings={}),
        "image_path": record["zarr"],
        "channels": [0],
        "extra_channel_indices": [1],
        "z_selection": "max",
        "method": "fast",
        "threshold": 100,
        "diameter": 14,
        "gpu": False,
        "output_dir": str(tmp_path / "analysis"),
        "synthetic_pixels": SimulatorPixels.recipe,
    }
    result = detect_objects.run({"input": inp}, {})
    np.testing.assert_array_equal(result["preprocess"]["image"][..., 1], 900)
    assert result["detect_objects"]["n_objects"] > 0
    checkpoint = json.loads(
        next((tmp_path / "analysis").rglob("detection_checkpoint.json")).read_text()
    )
    assert checkpoint["synthetic_pixels"] == SimulatorPixels.recipe
    params = detect_objects.segmentation_params(inp, {})
    assert detect_objects.segmentation_params_hash(
        params
    ) != detect_objects.segmentation_params_hash({**params, "z_selection": "mid"})


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
    result = detection.through(analysis, pixel_um=0.1)(record, 0, {})
    assert result["cells"][0]["area"] == 100
    assert result["cells"][0]["r"] == pytest.approx(np.sqrt(100 / np.pi))

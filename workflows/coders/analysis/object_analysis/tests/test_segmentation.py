"""read_images then segment_cellpose: what the detector is handed, and what comes back.

Cellpose is replaced by small stand-in models that answer with known
masks, so every test checks the steps' own work: reading the channels,
binning, the filters, the device it chose, and what it records.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest
import segment_cellpose
from helpers import load_step

read_images = load_step("object_analysis", "read_images")


def segmented(path, state, *, channels=None, gpu=True, **settings):
    """One file through read_images and segment_cellpose: the detection, and the image read."""
    given = {"image_path": str(path), "channels": channels, "gpu": gpu}
    data = read_images.run({"input": given, "metadata": {"verbose": 0}}, {})
    image = data["read_images"]["image"]
    detection = segment_cellpose.run(data, state, **settings)["segment_cellpose"]
    return {**detection, "image": image}


class _RecordingModel:
    def __init__(self):
        self.calls = []

    def eval(self, x, channel_axis=None, **kwargs):
        self.calls.append(
            {
                "input": np.asarray(x).copy(),
                "shape": x.shape,
                "channel_axis": channel_axis,
                "kwargs": kwargs,
            }
        )
        masks = np.zeros(x.shape[:2], dtype=np.int32)
        masks[1:3, 1:3] = 1
        return masks, None, None


class _PositionModel:
    def eval(self, x, channel_axis=None, **kwargs):
        masks = np.zeros(x.shape[:2], dtype=np.int32)
        masks[2, 3] = 1
        return masks, None, None


class _CornerPixelModel:
    def eval(self, x, channel_axis=None, **kwargs):
        masks = np.zeros(x.shape[:2], dtype=np.int32)
        masks[0, 0] = 1
        return masks, None, None


class _AreaModel:
    def eval(self, x, channel_axis=None, **kwargs):
        masks = np.zeros(x.shape[:2], dtype=np.int32)
        masks[1:3, 1:3] = 1
        masks[4:9, 4:9] = 2
        masks[10:20, 10:20] = 3
        return masks, None, None


def test_hands_cellpose_the_channels_last(tmp_path):
    import tifffile

    path = tmp_path / "three_channel.tif"
    tifffile.imwrite(
        path,
        np.zeros((3, 10, 12), dtype=np.uint8),
        metadata={"axes": "CYX"},
        photometric="minisblack",
    )
    model = _RecordingModel()
    out = segmented(path, {"model": model})

    assert model.calls[0]["channel_axis"] == -1
    assert "diameter" not in model.calls[0]["kwargs"]
    assert out["image"].shape == (10, 12, 3)


def test_takes_the_axes_from_the_file(tmp_path):
    """A file says what its axes are; the caller does not have to guess.

    A shape like (3, 10, 3) is ambiguous on its own: channel-first and
    channel-last look the same. The image's own metadata answers it.
    """
    import tifffile

    path = tmp_path / "declared.tif"
    image = np.zeros((3, 10, 3), dtype=np.uint8)
    image[0, 5, 1] = 17
    tifffile.imwrite(path, image, metadata={"axes": "CYX"})
    model = _RecordingModel()

    out = segmented(path, {"model": model}, channels=[0], gpu=False)

    assert out["image"].shape == (10, 3)
    assert int(out["image"][5, 1]) == 17
    assert model.calls[0]["shape"] == (10, 3)


def test_refuses_an_rgb_sample_image(tmp_path):
    """Channel-last samples are RGB to a TIFF reader, and stay refused."""
    import pytest
    import tifffile

    path = tmp_path / "rgb.tif"
    tifffile.imwrite(path, np.zeros((10, 12, 3), dtype=np.uint8))

    with pytest.raises(ValueError, match="3-sample .RGB. image"):
        segmented(path, {"model": _RecordingModel()})


def test_no_channel_axis_for_2d(tmp_path):
    import tifffile

    path = tmp_path / "gray.tif"
    tifffile.imwrite(path, np.zeros((10, 12), dtype=np.uint8))
    model = _RecordingModel()
    segmented(path, {"model": model})

    assert model.calls[0]["channel_axis"] is None


def test_filters_masks_by_min_and_max_area(tmp_path):
    import tifffile

    path = tmp_path / "gray.tif"
    tifffile.imwrite(path, np.zeros((24, 24), dtype=np.uint8))
    out = segmented(
        path,
        {"model": _AreaModel()},
        min_area_px=10,
        max_area_px=50,
    )

    assert out["n_raw_objects"] == 3
    assert out["n_objects"] == 1
    assert out["dropped_labels"] == [1, 3]
    assert out["area_filter"] == {
        "min_area_px": 10,
        "max_area_px": 50,
        "min_equivalent_diameter_um": None,
        "max_equivalent_diameter_um": None,
    }
    # The survivor keeps the detector's own label, so its id is the same
    # whatever the size bounds were.
    assert np.unique(out["masks"]).tolist() == [0, 2]
    assert int((out["masks"] == 2).sum()) == 25


def test_binning_downsamples_cellpose_input_without_upsampling(tmp_path):
    import tifffile

    path = tmp_path / "large.tif"
    tifffile.imwrite(path, np.zeros((20, 40), dtype=np.uint8))
    model = _RecordingModel()
    out = segmented(path, {"model": model}, segmentation_binning=4)

    assert model.calls[0]["shape"] == (5, 10)
    assert model.calls[0]["input"].dtype == np.float32
    assert out["masks"].shape == (20, 40)
    assert out["segmentation_resize"]["binning"] == 4
    assert out["segmentation_resize"]["input_size_px"] == [10, 5]
    assert out["segmentation_resize"]["scale"] == 0.25

    model = _RecordingModel()
    segmented(path, {"model": model}, segmentation_binning=1)
    assert model.calls[0]["shape"] == (20, 40)


def test_uses_segmentation_binning(tmp_path):
    import tifffile

    path = tmp_path / "large.tif"
    tifffile.imwrite(path, np.zeros((20, 40), dtype=np.uint8))
    model = _RecordingModel()
    out = segmented(path, {"model": model}, segmentation_binning=4)

    assert model.calls[0]["shape"] == (5, 10)
    assert out["masks"].shape == (20, 40)
    assert out["segmentation_resize"]["binning"] == 4
    assert out["segmentation_resize"]["input_size_px"] == [10, 5]


def test_area_downsamples_intensity_image(tmp_path):
    import tifffile

    path = tmp_path / "small.tif"
    image = np.arange(16, dtype=np.uint16).reshape(4, 4)
    tifffile.imwrite(path, image)
    model = _RecordingModel()
    segmented(path, {"model": model}, segmentation_binning=2)

    expected = np.array([[2.5, 4.5], [10.5, 12.5]], dtype=np.float32)
    np.testing.assert_allclose(model.calls[0]["input"], expected)


def test_binned_masks_are_not_smoothed(tmp_path):
    import tifffile

    path = tmp_path / "large.tif"
    tifffile.imwrite(path, np.zeros((8, 8), dtype=np.uint8))
    out = segmented(
        path,
        {"model": _CornerPixelModel()},
        segmentation_binning=4,
    )

    assert int((out["masks"] == 1).sum()) == 16
    assert "mask_smoothing_sigma_px" not in out["segmentation_resize"]


def test_upscaled_mask_position_is_original_space(tmp_path):
    import tifffile

    path = tmp_path / "large.tif"
    tifffile.imwrite(path, np.zeros((20, 40), dtype=np.uint8))
    out = segmented(path, {"model": _PositionModel()}, segmentation_binning=4)

    rows, cols = np.where(out["masks"] == 1)
    assert rows.min() == 8
    assert rows.max() == 11
    assert cols.min() == 12
    assert cols.max() == 15


def test_passes_cellpose_tuning_params(tmp_path):
    import tifffile

    path = tmp_path / "gray.tif"
    tifffile.imwrite(path, np.zeros((24, 24), dtype=np.uint8))
    model = _RecordingModel()
    out = segmented(
        path,
        {"model": model},
        cellprob_threshold=-1.0,
        flow_threshold=0.7,
        niter=2000,
        diameter=90,
        gpu=False,
    )

    assert model.calls[0]["kwargs"] == {
        "cellprob_threshold": -1.0,
        "flow_threshold": 0.7,
        "niter": 2000,
        "diameter": 90.0,
    }
    provenance = {
        key: out["detector_params"].pop(key)
        for key in ("cellpose_version", "cellpose_model", "torch_version")
    }
    assert set(provenance) == {"cellpose_version", "cellpose_model", "torch_version"}
    assert out["detector_params"] == {
        "method": "robust",
        "requested_gpu": False,
        "used_gpu": False,
        "device": "cpu",
        "cellprob_threshold": -1.0,
        "flow_threshold": 0.7,
        "niter": 2000,
        "diameter": 90.0,
    }


def test_prefers_gpu_and_falls_back_to_cpu(tmp_path, monkeypatch):
    import tifffile

    path = tmp_path / "gray.tif"
    tifffile.imwrite(path, np.zeros((8, 8), dtype=np.uint8))
    calls = []

    class _FakeDevice:
        def __init__(self, name):
            self.type = name
            self.name = name

    class _FakeCuda:
        @staticmethod
        def is_available():
            return True

    class _FakeMps:
        @staticmethod
        def is_available():
            return False

    class _FakeTorch:
        cuda = _FakeCuda()
        backends = types.SimpleNamespace(mps=_FakeMps())

        @staticmethod
        def device(name):
            return _FakeDevice(name)

    class _FakeCellposeModel:
        def __init__(self, gpu=False, device=None):
            device_name = getattr(device, "type", "cpu")
            calls.append((bool(gpu), device_name))
            if device_name == "cuda":
                raise RuntimeError("no cuda for test")
            self.device_name = device_name

        def eval(self, x, channel_axis=None, **kwargs):
            masks = np.zeros(x.shape[:2], dtype=np.int32)
            masks[1:4, 1:4] = 1
            return masks, None, None

    fake_models = types.SimpleNamespace(CellposeModel=_FakeCellposeModel)
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch)
    monkeypatch.setitem(sys.modules, "cellpose", types.SimpleNamespace(models=fake_models))

    out = segmented(path, {}, gpu=True)

    assert calls == [(True, "cuda"), (False, "cpu")]
    assert out["detector_params"]["requested_gpu"] is True
    assert out["detector_params"]["used_gpu"] is False
    assert out["detector_params"]["device"] == "cpu"


def test_uses_mps_when_cuda_is_unavailable(tmp_path, monkeypatch):
    import tifffile

    path = tmp_path / "gray.tif"
    tifffile.imwrite(path, np.zeros((8, 8), dtype=np.uint8))
    calls = []

    class _FakeDevice:
        def __init__(self, name):
            self.type = name

    class _FakeCuda:
        @staticmethod
        def is_available():
            return False

    class _FakeMps:
        @staticmethod
        def is_available():
            return True

    class _FakeTorch:
        cuda = _FakeCuda()
        backends = types.SimpleNamespace(mps=_FakeMps())

        @staticmethod
        def device(name):
            return _FakeDevice(name)

    class _FakeCellposeModel:
        def __init__(self, gpu=False, device=None):
            device_name = getattr(device, "type", "cpu")
            calls.append((bool(gpu), device_name))
            self.device_name = device_name

        def eval(self, x, channel_axis=None, **kwargs):
            masks = np.zeros(x.shape[:2], dtype=np.int32)
            masks[1:4, 1:4] = 1
            return masks, None, None

    fake_models = types.SimpleNamespace(CellposeModel=_FakeCellposeModel)
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch)
    monkeypatch.setitem(sys.modules, "cellpose", types.SimpleNamespace(models=fake_models))

    out = segmented(path, {}, gpu=True)

    assert calls == [(True, "mps")]
    assert out["detector_params"]["requested_gpu"] is True
    assert out["detector_params"]["used_gpu"] is True
    assert out["detector_params"]["device"] == "mps"


def test_rejects_invalid_area_filter(tmp_path):
    import tifffile

    path = tmp_path / "gray.tif"
    tifffile.imwrite(path, np.zeros((24, 24), dtype=np.uint8))
    with pytest.raises(ValueError, match="max object size must be >= min object size"):
        segmented(
            path,
            {"model": _AreaModel()},
            min_area_px=100,
            max_area_px=10,
        )


# ---------------------------------------------------------------------------
# The overlap guard
# ---------------------------------------------------------------------------


def _labelled(height, width, boxes):
    """A mask image with one label per (row0, row1, col0, col1) box."""
    masks = np.zeros((height, width), dtype=np.int32)
    for index, (r0, r1, c0, c1) in enumerate(boxes, start=1):
        masks[r0:r1, c0:c1] = index
    return masks


def test_border_margin_of_none_or_zero_keeps_everything():
    filter_masks_by_border = segment_cellpose._filter_by_border

    masks = _labelled(20, 20, [(0, 3, 0, 3), (8, 12, 8, 12)])
    for margin in (None, 0):
        kept, dropped = filter_masks_by_border(masks, border_margin_px=margin)
        assert dropped == []
        assert int(kept.max()) == 2


def test_objects_in_the_border_band_are_dropped_and_the_rest_keep_their_labels():
    filter_masks_by_border = segment_cellpose._filter_by_border

    masks = _labelled(20, 20, [(0, 3, 0, 3), (8, 12, 8, 12), (17, 20, 17, 20)])
    kept, dropped = filter_masks_by_border(masks, border_margin_px=4)

    assert dropped == [1, 3]
    assert np.unique(kept).tolist() == [0, 2], "the survivor keeps its own label"
    assert set(np.unique(kept[8:12, 8:12].ravel()).tolist()) == {2}


def test_a_border_margin_and_a_size_bound_together_name_dropped_labels_correctly(tmp_path):
    """Both filters drop labels from the detector's own numbering, so the
    union of the two lists names real objects rather than a renumbered
    intermediate."""
    filter_masks_by_area = segment_cellpose.filter_by_area
    filter_masks_by_border = segment_cellpose._filter_by_border

    masks = _labelled(20, 20, [(0, 3, 0, 3), (8, 12, 8, 12), (14, 15, 14, 15), (17, 20, 17, 20)])
    kept, by_border = filter_masks_by_border(masks, border_margin_px=4)
    kept, by_area = filter_masks_by_area(kept, min_area_px=4)
    assert by_border == [1, 4]
    assert by_area == [3]
    assert np.unique(kept).tolist() == [0, 2]


def test_an_object_reaching_into_the_band_is_dropped_whole():
    """Overlap duplicates a whole object, so half of one is not worth keeping."""
    filter_masks_by_border = segment_cellpose._filter_by_border

    masks = _labelled(20, 20, [(2, 10, 2, 10)])
    kept, dropped = filter_masks_by_border(masks, border_margin_px=4)

    assert dropped == [1]
    assert int(kept.max()) == 0


def test_a_margin_wider_than_the_tile_is_refused():
    filter_masks_by_border = segment_cellpose._filter_by_border

    masks = _labelled(20, 20, [(8, 12, 8, 12)])
    with pytest.raises(ValueError, match="leaves no interior"):
        filter_masks_by_border(masks, border_margin_px=10)
    with pytest.raises(ValueError, match="must be >= 0"):
        filter_masks_by_border(masks, border_margin_px=-1)


def test_drops_border_objects_and_records_the_margin(tmp_path):
    import tifffile

    path = tmp_path / "tile.tif"
    tifffile.imwrite(path, np.zeros((20, 20), dtype=np.uint8))
    given = _labelled(20, 20, [(0, 3, 0, 3), (8, 12, 8, 12)])

    class _GivenMasks:
        def eval(self, x, channel_axis=None, **kwargs):
            return given, None, None

    model = _GivenMasks()

    out = segmented(path, {"model": model}, border_margin_px=4)

    assert out["n_raw_objects"] == 2
    assert out["n_objects"] == 1
    assert out["dropped_labels"] == [1]
    assert out["border_filter"] == {"border_margin_px": 4}


def test_a_model_that_fell_back_to_the_cpu_is_offered_the_gpu_again(tmp_path, monkeypatch):
    """The card was full for a moment; the session must not stay on the CPU.

    Measured on the operator's PC: a tile test stopped by hand and another
    started a second later loaded its model while the card still held the
    dead worker's memory, fell back to the CPU without a word, and the
    cached CPU model then segmented nine fields at ten minutes each.
    """
    import tifffile

    path = tmp_path / "gray.tif"
    tifffile.imwrite(path, np.zeros((8, 8), dtype=np.uint8))
    calls = []
    cuda_attempts = {"n": 0}

    class _FakeDevice:
        def __init__(self, name):
            self.type = name

    class _FakeCuda:
        @staticmethod
        def is_available():
            return True

    class _FakeMps:
        @staticmethod
        def is_available():
            return False

    class _FakeTorch:
        cuda = _FakeCuda()
        backends = types.SimpleNamespace(mps=_FakeMps())

        @staticmethod
        def device(name):
            return _FakeDevice(name)

    class _FakeCellposeModel:
        def __init__(self, gpu=False, device=None):
            device_name = getattr(device, "type", "cpu")
            calls.append((bool(gpu), device_name))
            if device_name == "cuda":
                cuda_attempts["n"] += 1
                if cuda_attempts["n"] == 1:
                    raise RuntimeError("CUDA out of memory (the card was full for a moment)")
            self.device_name = device_name

        def eval(self, x, channel_axis=None, **kwargs):
            masks = np.zeros(x.shape[:2], dtype=np.int32)
            masks[1:4, 1:4] = 1
            return masks, None, None

    fake_models = types.SimpleNamespace(CellposeModel=_FakeCellposeModel)
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch)
    monkeypatch.setitem(sys.modules, "cellpose", types.SimpleNamespace(models=fake_models))

    state = {}
    first = segmented(path, state, gpu=True)
    assert first["detector_params"]["device"] == "cpu"
    second = segmented(path, state, gpu=True)
    assert second["detector_params"]["device"] == "cuda"
    assert second["detector_params"]["used_gpu"] is True
    assert calls == [(True, "cuda"), (False, "cpu"), (True, "cuda")]
    # And once on the card it stays there: no reload per field.
    third = segmented(path, state, gpu=True)
    assert third["detector_params"]["device"] == "cuda"
    assert len(calls) == 3

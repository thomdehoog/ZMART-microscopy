from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _contracts import validate_targets, validate_tile_detection  # noqa: E402
from _detection_checkpoint import (  # noqa: E402
    area_filter_params,
    segmentation_params,
    segmentation_params_hash,
)


WORKFLOW = Path(__file__).resolve().parents[1]
STEPS_DIR = WORKFLOW / "steps"
CLASSICAL_YAML = WORKFLOW / "pipelines" / "object_analysis.yaml"
DETECTION_YAML = WORKFLOW / "pipelines" / "object_detection.yaml"


def _load_step(name: str):
    path = STEPS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect_objects = _load_step("detect_objects")
extract_classical_features = _load_step("extract_classical_features")
build_object_table = _load_step("build_object_table")


def _load_target_discovery_step():
    path = WORKFLOW.parent / "target_discovery" / "steps" / "select_targets.py"
    if not path.is_file():
        # ZMART vendors only the workflows it runs; target_discovery is not
        # one of them. See ../../README.md for what was taken and why.
        pytest.skip("target_discovery is not part of this checkout")
    spec = importlib.util.spec_from_file_location("select_targets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def _write_synthetic_tile(tmp_path):
    import tifffile

    image = np.zeros((40, 48), dtype=np.uint8)
    image[5:11, 6:12] = 80
    image[20:30, 25:35] = 160
    path = tmp_path / "tile.ome.tiff"
    tifffile.imwrite(path, image, photometric="minisblack")
    return path


def _write_immunohistochemistry_tile(tmp_path):
    import tifffile
    from skimage.data import immunohistochemistry

    # The sample is a true RGB photograph. A microscope writes channels,
    # never samples, so it is stored channel-first with its axes declared --
    # which is what makes it stand in for a three-channel tile at all.
    image = immunohistochemistry()
    path = tmp_path / "immunohistochemistry.tif"
    tifffile.imwrite(
        path, np.moveaxis(image, -1, 0), metadata={"axes": "CYX"}
    )
    return path, image


def _payload(image_path: Path, **extra):
    payload = {
        "image_path": str(image_path),
        "tile_id": ["R0", 3, 7],
        "tile_stage_xy_um": [1000.0, 2000.0],
        "tile_zwide_um": 250.0,
        "source_pixel_size_um": [2.0, 3.0],
        "source_image_size_px": [48, 40],
        "image_to_stage": [[1.0, 0.0], [0.0, 1.0]],
        "gpu": False,
    }
    payload.update(extra)
    return payload


def _run_classical(tmp_path, **payload_extra):
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(image_path, **payload_extra),
        "metadata": {"verbose": 0},
    }
    state = {"model": _StubCellposeModel()}
    pipeline_data = detect_objects.run(pipeline_data, state)
    pipeline_data = extract_classical_features.run(pipeline_data, {})
    return build_object_table.run(pipeline_data, {})


def _run_engine_workflow(name: str, yaml_path: Path, payload: dict, timeout=180):
    import time
    from engine import Engine

    with Engine() as engine:
        engine.register(name, str(yaml_path))
        engine.submit(name, payload)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            results = engine.results(name)
            if results:
                return results[0]
            status = engine.status(name)
            if status["failed"]:
                failure = status["failures"][0]
                raise AssertionError(f"{failure['step']}: {failure['error']}")
            time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {name}")


def test_classical_object_analysis_end_to_end_with_stub(tmp_path):
    result = _run_classical(tmp_path)
    tile = validate_tile_detection(result["object_analysis"])
    props = tile["objects"]["properties"]

    assert tile["objects"]["n_objects"] == 2
    assert props["label"] == [1, 2]
    assert props["object_id"] == [
        "R0_r003_c007_obj00001",
        "R0_r003_c007_obj00002",
    ]
    assert props["tile_name"] == ["R0_r003_c007", "R0_r003_c007"]
    assert "crop_height_px" not in props
    assert "crop_width_px" not in props
    assert "crop_path" not in props
    assert "embeddings" not in tile["objects"]
    assert props["stage_x_um"] == pytest.approx([969.0, 1011.0])
    assert props["stage_y_um"] == pytest.approx([1962.5, 2013.5])
    assert "centroid-0" not in props
    assert "bbox-0" not in props
    assert "preprocess" not in result
    assert "segment" not in result
    assert "extract_features" not in result
    assert "masks" not in result["detect_objects"]


def test_detection_checkpoint_hash_ignores_runtime_and_area_filter():
    base = {
        "channels": None,
        "channel_axis": None,
        "cellprob_threshold": 0.0,
        "flow_threshold": 0.4,
        "niter": None,
        "diameter": None,
        "segmentation_binning": None,
    }

    assert segmentation_params_hash(base | {"gpu": False, "min_area_px": 10}) == (
        segmentation_params_hash(base | {"gpu": True, "min_area_px": 2000})
    )
    assert segmentation_params_hash(base | {"segmentation_binning": 4}) != (
        segmentation_params_hash(base | {"segmentation_binning": 2})
    )
    assert segmentation_params_hash(base | {"channel_axis": 0}) != (
        segmentation_params_hash(base | {"channel_axis": -1})
    )
    assert segmentation_params_hash(base | {"channel_axis": 2}) == (
        segmentation_params_hash(base | {"channel_axis": -1})
    )
    assert segmentation_params_hash(base | {"unused_legacy_key": 1.0}) == (
        segmentation_params_hash(base | {"unused_legacy_key": None})
    )


def test_segmentation_params_normalizes_and_validates_channel_axis():
    assert segmentation_params({"channel_axis": 2}, {})["channel_axis"] == -1
    assert segmentation_params({"channel_axis": -1}, {})["channel_axis"] == -1
    assert segmentation_params({}, {"channel_axis": 0})["channel_axis"] == 0
    with pytest.raises(ValueError, match="channel_axis must be"):
        segmentation_params({"channel_axis": 1}, {})


def test_area_filter_rejects_ambiguous_pixel_and_diameter_thresholds():
    with pytest.raises(ValueError, match="not both"):
        area_filter_params(
            {"source_pixel_size_um": [0.5, 0.5]},
            {"min_area_px": 10, "min_equivalent_diameter_um": 5.0},
        )


def test_the_pipelines_register(tmp_path):
    """Every shipped YAML parses and resolves its steps."""
    sys.path.insert(0, str(WORKFLOW.parents[2]))
    from engine import Engine

    engine = Engine()
    try:
        engine.register("classical", str(CLASSICAL_YAML))
        engine.register("detection", str(DETECTION_YAML))
    finally:
        engine.shutdown()


def test_object_analysis_hands_off_to_target_discovery(tmp_path):
    result = _run_classical(tmp_path)
    tile = result["object_analysis"]
    select_targets = _load_target_discovery_step()

    discovery_pd = {
        "input": {
            "tiles": [tile],
            "feature": "area",
            "direction": "high",
            "n_per_tile": 1,
        },
        "metadata": {"verbose": 0},
    }
    targets = select_targets.run(discovery_pd, {})["target_discovery"]
    validated = validate_targets(targets)

    assert len(validated["targets"]) == 1
    assert validated["targets"][0]["object_label"] == 2


@pytest.mark.cellpose
@pytest.mark.pooch
@pytest.mark.slow
def test_real_cellpose_object_analysis_end_to_end(tmp_path):
    image_path, image = _write_immunohistochemistry_tile(tmp_path)

    result = _run_engine_workflow(
        "object_analysis_real_cellpose",
        CLASSICAL_YAML,
        _payload(
            image_path,
            tile_id=["IHC", 0, 0],
            tile_stage_xy_um=[10000.0, 15000.0],
            source_pixel_size_um=[0.5, 0.5],
            source_image_size_px=[int(image.shape[1]), int(image.shape[0])],
            image_to_stage=[[0.0, -1.0], [1.0, 0.0]],
            channels=None,
            gpu=True,
        ),
    )
    tile = validate_tile_detection(result["object_analysis"])

    assert tile["objects"]["n_objects"] > 0
    assert tile["objects"]["properties"]["object_id"][0].startswith("IHC_r000_c000_obj")
    assert all(
        isinstance(value, float)
        for value in tile["objects"]["properties"]["stage_x_um"]
    )


@pytest.mark.cellpose
@pytest.mark.pooch
@pytest.mark.slow
def test_real_cpsam_multichannel_immunohistochemistry_end_to_end(tmp_path):
    image_path, image = _write_immunohistochemistry_tile(tmp_path)

    result = _run_engine_workflow(
        "object_analysis_real_cpsam_multichannel",
        CLASSICAL_YAML,
        _payload(
            image_path,
            tile_id=["IHC", 0, 0],
            tile_stage_xy_um=[5000.0, 6000.0],
            source_pixel_size_um=[0.5, 0.5],
            source_image_size_px=[int(image.shape[1]), int(image.shape[0])],
            image_to_stage=[[1.0, 0.0], [0.0, 1.0]],
            channels=None,
            gpu=True,
        ),
        timeout=240,
    )
    tile = validate_tile_detection(result["object_analysis"])
    props = tile["objects"]["properties"]

    assert tile["objects"]["n_objects"] > 0
    for channel in range(3):
        key = f"intensity_mean_c{channel}"
        assert key in props
        assert len(props[key]) == tile["objects"]["n_objects"]
    assert props["intensity_mean"] == props["intensity_mean_c0"]


class _StubCellposeModel:
    def eval(self, x, channel_axis=None, **kwargs):
        masks = np.zeros(x.shape[:2], dtype=np.int32)
        masks[5:11, 6:12] = 1
        masks[20:30, 25:35] = 2
        return masks, None, None


class _ShapeAgnosticCellposeModel:
    def eval(self, x, channel_axis=None, **kwargs):
        return np.zeros(x.shape[:2], dtype=np.int32), None, None

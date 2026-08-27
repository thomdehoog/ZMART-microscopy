from __future__ import annotations

import importlib.util
import json
import os
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
from _intensity_scale import compute_foreground_intensity_scale  # noqa: E402
from _object_crops import extract_object_crops  # noqa: E402


WORKFLOW = Path(__file__).resolve().parents[1]
STEPS_DIR = WORKFLOW / "steps"
CLASSICAL_YAML = WORKFLOW / "pipelines" / "object_analysis.yaml"
DEEP_YAML = WORKFLOW / "pipelines" / "object_analysis_deep.yaml"
DETECTION_YAML = WORKFLOW / "pipelines" / "object_detection.yaml"
FEATURES_DEEP_YAML = WORKFLOW / "pipelines" / "object_features_deep.yaml"


def _load_step(name: str):
    path = STEPS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect_objects = _load_step("detect_objects")
load_detected_objects = _load_step("load_detected_objects")
extract_classical_features = _load_step("extract_classical_features")
extract_deep_features = _load_step("extract_deep_features")
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


def _mask_major_axis(mask):
    rows, cols = np.nonzero(mask)
    coords = np.column_stack([cols, rows]).astype(float)
    coords -= coords.mean(axis=0)
    cov = np.cov(coords.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    major_idx = int(np.argmax(eigvals))
    angle = float(np.degrees(np.arctan2(
        eigvecs[1, major_idx],
        eigvecs[0, major_idx],
    )) % 180.0)
    major = float(eigvals[major_idx])
    minor = float(eigvals[1 - major_idx])
    eccentricity = float(np.sqrt(max(0.0, 1.0 - max(minor, 0.0) / major)))
    return angle, eccentricity


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


def test_deep_path_writes_position_based_crop_artifacts(tmp_path):
    output_dir = tmp_path / "analysis" / "object_analysis" / "run_001"
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(
            image_path,
            output_dir=str(output_dir),
            backend="mock",
            embedding_dim=6,
        ),
        "metadata": {"verbose": 0},
    }
    state = {"model": _StubCellposeModel()}
    pipeline_data = detect_objects.run(pipeline_data, state)
    pipeline_data = extract_classical_features.run(pipeline_data, {})
    pipeline_data = extract_deep_features.run(pipeline_data, {}, crop_size_px=10)
    result = build_object_table.run(pipeline_data, {})
    props = result["object_analysis"]["objects"]["properties"]

    masks_path = output_dir / "tiles" / "R0_r003_c007" / "masks.tif"
    object_dir = output_dir / "objects" / "R0_r003_c007_obj00001"
    assert masks_path.exists()
    assert (object_dir / "crop.tif").exists()
    assert (object_dir / "mask.tif").exists()
    assert props["crop_path"][0] == str(object_dir / "crop.tif")
    assert props["mask_path"][0] == str(object_dir / "mask.tif")


def test_detection_checkpoint_can_reenter_feature_extraction(tmp_path):
    detection_dir = tmp_path / "object_detection"
    features_dir = tmp_path / "object_features"
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(
            image_path,
            output_dir=str(detection_dir),
        ),
        "metadata": {"verbose": 0},
    }

    detection_data = detect_objects.run(pipeline_data, {"model": _StubCellposeModel()})
    detection = detection_data["detect_objects"]
    checkpoint_path = detection["artifacts"]["detection_checkpoint_json"]
    masks_path = detection["artifacts"]["masks_tif"]

    assert Path(checkpoint_path).exists()
    assert Path(masks_path).exists()

    feature_data = {
        "input": {
            "detection_checkpoint_path": checkpoint_path,
            "segmentation_params_hash": detection["segmentation_params_hash"],
            "output_dir": str(features_dir),
            "backend": "mock",
            "embedding_dim": 6,
        },
        "metadata": {"verbose": 0},
    }
    feature_data = load_detected_objects.run(feature_data, {})
    feature_data = extract_classical_features.run(feature_data, {})
    feature_data = extract_deep_features.run(feature_data, {}, crop_size_px=12)
    result = build_object_table.run(feature_data, {})["object_analysis"]
    props = result["objects"]["properties"]
    embeddings = result["objects"]["embeddings"]

    assert result["objects"]["n_objects"] == 2
    assert props["label"] == [1, 2]
    assert embeddings["backend"] == "mock"
    assert embeddings["label"] == props["label"]
    assert len(embeddings["vectors"]) == 2
    assert len(embeddings["vectors"][0]) == 6
    assert (features_dir / "objects" / "R0_r003_c007_obj00001" / "crop.tif").exists()


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


def test_ambiguous_channel_axis_round_trips_through_detection_checkpoint(tmp_path):
    import tifffile

    # (3, 10, 3) cannot be told channel-first from channel-last by shape,
    # so the file declares its axes rather than the caller asserting them.
    image = np.zeros((3, 10, 3), dtype=np.uint8)
    image[0, 5, 1] = 11
    image_path = tmp_path / "ambiguous.tif"
    tifffile.imwrite(image_path, image, metadata={"axes": "CYX"})
    output_dir = tmp_path / "detection"
    pipeline_data = {
        "input": _payload(
            image_path,
            channel_axis=0,
            channels=[0],
            output_dir=str(output_dir),
            source_image_size_px=[3, 10],
        ),
        "metadata": {"verbose": 0},
    }

    detected = detect_objects.run(
        pipeline_data, {"model": _ShapeAgnosticCellposeModel()}
    )["detect_objects"]
    assert detected["image"].shape == (10, 3)
    assert detected["segmentation_params"]["channel_axis"] == 0

    checkpoint_path = detected["artifacts"]["detection_checkpoint_json"]
    checkpoint = json.loads(Path(checkpoint_path).read_text())
    assert checkpoint["segmentation_params"]["channel_axis"] == 0

    loaded = load_detected_objects.run(
        {
            "input": {
                "detection_checkpoint_path": checkpoint_path,
                "segmentation_params_hash": detected["segmentation_params_hash"],
            },
            "metadata": {"verbose": 0},
        },
        {},
    )["detect_objects"]
    assert loaded["image"].shape == (10, 3)
    assert int(loaded["image"][5, 1]) == 11
    assert loaded["segmentation_params"]["channel_axis"] == 0

    checkpoint["segmentation_params"]["channel_axis"] = -1
    Path(checkpoint_path).write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(ValueError, match="may be corrupt"):
        load_detected_objects.run(
            {
                "input": {
                    "detection_checkpoint_path": checkpoint_path,
                    "segmentation_params_hash": detected[
                        "segmentation_params_hash"
                    ],
                },
                "metadata": {"verbose": 0},
            },
            {},
        )


def test_checkpoint_reentry_can_retune_area_filter_without_redetection(tmp_path):
    detection_dir = tmp_path / "object_detection"
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(
            image_path,
            output_dir=str(detection_dir),
        ),
        "metadata": {"verbose": 0},
    }
    detection_data = detect_objects.run(pipeline_data, {"model": _StubCellposeModel()})
    detection = detection_data["detect_objects"]

    feature_data = {
        "input": {
            "detection_checkpoint_path": detection["artifacts"]["detection_checkpoint_json"],
            "segmentation_params_hash": detection["segmentation_params_hash"],
            "min_area_px": 80,
        },
        "metadata": {"verbose": 0},
    }
    feature_data = load_detected_objects.run(feature_data, {})

    assert feature_data["detect_objects"]["n_raw_objects"] == 2
    assert feature_data["detect_objects"]["n_objects"] == 1
    assert feature_data["detect_objects"]["dropped_labels"] == [1]


def test_checkpoint_reentry_defaults_to_stored_area_filter(tmp_path):
    detection_dir = tmp_path / "object_detection"
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(
            image_path,
            output_dir=str(detection_dir),
            min_area_px=80,
        ),
        "metadata": {"verbose": 0},
    }
    detection_data = detect_objects.run(pipeline_data, {"model": _StubCellposeModel()})
    detection = detection_data["detect_objects"]

    feature_data = {
        "input": {
            "detection_checkpoint_path": detection["artifacts"]["detection_checkpoint_json"],
            "segmentation_params_hash": detection["segmentation_params_hash"],
        },
        "metadata": {"verbose": 0},
    }
    feature_data = load_detected_objects.run(feature_data, {})

    assert feature_data["detect_objects"]["n_raw_objects"] == 2
    assert feature_data["detect_objects"]["n_objects"] == 1
    assert feature_data["detect_objects"]["area_filter"]["min_area_px"] == 80
    assert feature_data["detect_objects"]["dropped_labels"] == [1]


def test_checkpoint_reentry_can_retune_equivalent_diameter_filter(tmp_path):
    detection_dir = tmp_path / "object_detection"
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(
            image_path,
            output_dir=str(detection_dir),
        ),
        "metadata": {"verbose": 0},
    }
    detection_data = detect_objects.run(pipeline_data, {"model": _StubCellposeModel()})
    detection = detection_data["detect_objects"]

    # With source_pixel_size_um=[2, 3], a 20 um equivalent-diameter floor
    # converts to ceil(pi * 10^2 / 6) = 53 px. The 36 px object drops; the
    # 100 px object remains.
    feature_data = {
        "input": {
            "detection_checkpoint_path": detection["artifacts"]["detection_checkpoint_json"],
            "segmentation_params_hash": detection["segmentation_params_hash"],
            "min_equivalent_diameter_um": 20.0,
        },
        "metadata": {"verbose": 0},
    }
    feature_data = load_detected_objects.run(feature_data, {})

    area_filter = feature_data["detect_objects"]["area_filter"]
    assert area_filter["min_area_px"] == 53
    assert area_filter["min_equivalent_diameter_um"] == 20.0
    assert feature_data["detect_objects"]["n_raw_objects"] == 2
    assert feature_data["detect_objects"]["n_objects"] == 1
    assert feature_data["detect_objects"]["dropped_labels"] == [1]


def test_area_filter_rejects_ambiguous_pixel_and_diameter_thresholds():
    with pytest.raises(ValueError, match="not both"):
        area_filter_params(
            {"source_pixel_size_um": [0.5, 0.5]},
            {"min_area_px": 10, "min_equivalent_diameter_um": 5.0},
        )


def test_detection_checkpoint_hash_mismatch_rejects_stale_masks(tmp_path):
    detection_dir = tmp_path / "object_detection"
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(image_path, output_dir=str(detection_dir)),
        "metadata": {"verbose": 0},
    }
    detection_data = detect_objects.run(pipeline_data, {"model": _StubCellposeModel()})
    checkpoint_path = detection_data["detect_objects"]["artifacts"]["detection_checkpoint_json"]

    with pytest.raises(ValueError, match="does not match"):
        load_detected_objects.run(
            {
                "input": {
                    "detection_checkpoint_path": checkpoint_path,
                    "segmentation_params_hash": "definitely-not-the-current-hash",
                },
                "metadata": {"verbose": 0},
            },
            {},
        )


def test_detection_checkpoint_rejects_changed_image_file(tmp_path):
    detection_dir = tmp_path / "object_detection"
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(image_path, output_dir=str(detection_dir)),
        "metadata": {"verbose": 0},
    }
    detection_data = detect_objects.run(pipeline_data, {"model": _StubCellposeModel()})
    checkpoint_path = detection_data["detect_objects"]["artifacts"]["detection_checkpoint_json"]

    import tifffile

    tifffile.imwrite(image_path, np.zeros((40, 48), dtype=np.uint8))

    with pytest.raises(ValueError, match="image hash"):
        load_detected_objects.run(
            {
                "input": {
                    "detection_checkpoint_path": checkpoint_path,
                    "segmentation_params_hash": detection_data["detect_objects"]["segmentation_params_hash"],
                },
                "metadata": {"verbose": 0},
            },
            {},
        )


def test_split_detection_features_engine_path_with_mock_backend(tmp_path, monkeypatch):
    import textwrap
    import time
    import yaml
    from engine import Engine

    fake_pkg = tmp_path / "fakepkgs" / "cellpose"
    fake_pkg.mkdir(parents=True)
    (fake_pkg / "__init__.py").write_text("", encoding="utf-8")
    (fake_pkg / "models.py").write_text(
        textwrap.dedent(
            """
            import numpy as np

            class CellposeModel:
                def __init__(self, gpu=False):
                    self.gpu = gpu

                def eval(self, x, channel_axis=None, **kwargs):
                    masks = np.zeros(x.shape[:2], dtype=np.int32)
                    masks[5:11, 6:12] = 1
                    masks[20:30, 25:35] = 2
                    return masks, None, None
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PYTHONPATH",
        str(tmp_path / "fakepkgs")
        + (os.pathsep + sys.path[0] if sys.path else ""),
    )

    wrapper_dir = tmp_path / "steps"
    wrapper_dir.mkdir()
    for name in (
        "detect_objects",
        "load_detected_objects",
        "extract_classical_features",
        "extract_deep_features",
        "build_object_table",
    ):
        real_path = (STEPS_DIR / f"{name}.py").as_posix()
        (wrapper_dir / f"{name}.py").write_text(
            textwrap.dedent(
                f"""
                import importlib.util
                spec = importlib.util.spec_from_file_location("_real_{name}", r"{real_path}")
                _real = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(_real)
                METADATA = {{"environment": None, "max_workers": 1}}

                def run(pipeline_data, state, **params):
                    return _real.run(pipeline_data, state, **params)
                """
            ),
            encoding="utf-8",
        )

    detection_yaml = tmp_path / "object_detection.yaml"
    detection_yaml.write_text(
        yaml.safe_dump({
            "metadata": {"functions_dir": str(wrapper_dir), "verbose": 0},
            "object_detection": [
                {"detect_objects": {
                    "channels": None,
                    "cellprob_threshold": 0.0,
                    "flow_threshold": 0.4,
                    "niter": None,
                    "diameter": None,
                    "segmentation_binning": 1,
                    "min_area_px": 80,
                    "max_area_px": None,
                    "persist_only": True,
                }},
            ],
        }, sort_keys=False),
        encoding="utf-8",
    )
    features_yaml = tmp_path / "object_features.yaml"
    features_yaml.write_text(
        yaml.safe_dump({
            "metadata": {"functions_dir": str(wrapper_dir), "verbose": 0},
            "object_features": [
                {"load_detected_objects": {"min_area_px": 0, "max_area_px": None}},
                {"extract_classical_features": None},
                {"extract_deep_features": {
                    "backend": "mock",
                    "embedding_dim": 6,
                    "crop_size_px": 12,
                    "mask": True,
                }},
                {"build_object_table": None},
            ],
        }, sort_keys=False),
        encoding="utf-8",
    )

    image_path = _write_synthetic_tile(tmp_path)
    detection_output = tmp_path / "object_detection"
    features_output = tmp_path / "object_features"
    payload = _payload(image_path, output_dir=str(detection_output), gpu=True)

    with Engine(execution_timeout=30) as engine:
        engine.register("object_detection_mock", str(detection_yaml))
        engine.submit("object_detection_mock", payload)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            results = engine.results("object_detection_mock")
            if results:
                detection_result = results[0]
                break
            assert not engine.status("object_detection_mock")["failed"]
            time.sleep(0.1)
        else:
            raise AssertionError("Timed out waiting for object_detection_mock")

        detection = detection_result["detect_objects"]
        assert "masks" not in detection
        checkpoint_path = detection["artifacts"]["detection_checkpoint_json"]
        expected_hash = detection["segmentation_params_hash"]

        engine.register("object_features_mock", str(features_yaml))
        engine.submit(
            "object_features_mock",
            {
                "detection_checkpoint_path": checkpoint_path,
                "segmentation_params_hash": expected_hash,
                "output_dir": str(features_output),
            },
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            results = engine.results("object_features_mock")
            if results:
                features_result = results[0]
                break
            assert not engine.status("object_features_mock")["failed"]
            time.sleep(0.1)
        else:
            raise AssertionError("Timed out waiting for object_features_mock")

    tile = features_result["object_analysis"]
    assert tile["objects"]["n_objects"] == 2
    assert tile["objects"]["embeddings"]["backend"] == "mock"


def test_fixed_crop_size_is_used_for_every_object(tmp_path):
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(image_path),
        "metadata": {"verbose": 0},
    }
    pipeline_data = detect_objects.run(pipeline_data, {"model": _StubCellposeModel()})
    crops = extract_object_crops(
        image=pipeline_data["detect_objects"]["image_2d"],
        masks=pipeline_data["detect_objects"]["masks"],
        tile_id=pipeline_data["input"]["tile_id"],
        crop_size_px=24,
        mask=False,
    )

    assert crops["crop_policy"] == {
        "crop_size_px": 24,
        "mask": False,
        "drop_incomplete": True,
        "align_orientation": False,
        "min_eccentricity_to_align": 0.4,
        "orientation_target_deg": 45.0,
    }
    assert crops["skipped_incomplete_labels"] == [1]
    assert [obj["label"] for obj in crops["objects"]] == [2]
    assert [obj["crop_height_px"] for obj in crops["objects"]] == [24]
    assert [obj["crop_width_px"] for obj in crops["objects"]] == [24]
    assert crops["objects"][0]["crop_aligned_orientation"] is False
    assert crops["objects"][0]["crop_rotation_deg"] == 0.0


def test_aligned_crop_rotates_elongated_object_to_diagonal():
    image = np.ones((80, 80), dtype=np.uint8)
    masks = np.zeros((80, 80), dtype=np.int32)
    masks[38:42, 20:60] = 1

    crops = extract_object_crops(
        image=image,
        masks=masks,
        tile_id=["R0", 0, 0],
        crop_size_px=48,
        mask=True,
        align_orientation=True,
        min_eccentricity_to_align=0.0,
    )

    assert crops["skipped_incomplete_labels"] == []
    obj = crops["objects"][0]
    angle, eccentricity = _mask_major_axis(obj["crop_mask"])
    assert obj["crop_aligned_orientation"] is True
    assert obj["crop_eccentricity"] > 0.8
    assert obj["crop_oriented_extent_px"] < 48
    assert eccentricity > 0.8
    assert angle == pytest.approx(45.0, abs=3.0)
    assert np.all(obj["crop_image"][obj["crop_mask"] == 0] == 0)


def test_orientation_alignment_does_not_change_crop_acceptance():
    image = np.ones((96, 96), dtype=np.uint8)
    masks = np.zeros((96, 96), dtype=np.int32)
    masks[46:50, 18:78] = 1

    unaligned = extract_object_crops(
        image=image,
        masks=masks,
        tile_id=["R0", 0, 0],
        crop_size_px=48,
        mask=True,
        align_orientation=False,
        drop_incomplete=True,
    )
    aligned = extract_object_crops(
        image=image,
        masks=masks,
        tile_id=["R0", 0, 0],
        crop_size_px=48,
        mask=True,
        align_orientation=True,
        min_eccentricity_to_align=0.0,
        drop_incomplete=True,
    )

    assert unaligned["objects"] == []
    assert unaligned["skipped_incomplete_labels"] == [1]
    assert aligned["objects"] == []
    assert aligned["skipped_incomplete_labels"] == [1]


def test_round_crop_is_not_orientation_aligned():
    image = np.ones((64, 64), dtype=np.uint8)
    masks = np.zeros((64, 64), dtype=np.int32)
    rr, cc = np.ogrid[:64, :64]
    masks[(rr - 32) ** 2 + (cc - 32) ** 2 <= 8 ** 2] = 1

    crops = extract_object_crops(
        image=image,
        masks=masks,
        tile_id=["R0", 0, 0],
        crop_size_px=32,
        mask=True,
        align_orientation=True,
        min_eccentricity_to_align=0.4,
    )

    obj = crops["objects"][0]
    assert obj["crop_aligned_orientation"] is False
    assert obj["crop_rotation_deg"] == 0.0
    assert obj["crop_eccentricity"] < 0.4
    assert obj["crop_oriented_extent_px"] is not None


def test_masked_crop_keeps_padded_context_when_object_is_complete():
    image = np.ones((20, 20), dtype=np.uint8)
    masks = np.zeros((20, 20), dtype=np.int32)
    masks[2:6, 2:6] = 1

    crops = extract_object_crops(
        image=image,
        masks=masks,
        tile_id=["R0", 0, 0],
        crop_size_px=12,
        mask=True,
        drop_incomplete=True,
    )

    assert crops["skipped_incomplete_labels"] == []
    assert [obj["label"] for obj in crops["objects"]] == [1]
    obj = crops["objects"][0]
    assert obj["crop_complete"] is True
    assert obj["crop_in_bounds"] is False
    assert obj["object_complete"] is True
    assert obj["object_fits_crop"] is True
    assert obj["crop_origin_row_px"] < 0
    assert obj["crop_origin_col_px"] < 0
    assert np.all(obj["crop_image"][obj["crop_mask"] == 0] == 0)


def test_unmasked_crop_drops_padded_context():
    image = np.ones((20, 20), dtype=np.uint8)
    masks = np.zeros((20, 20), dtype=np.int32)
    masks[2:6, 2:6] = 1

    crops = extract_object_crops(
        image=image,
        masks=masks,
        tile_id=["R0", 0, 0],
        crop_size_px=12,
        mask=False,
        drop_incomplete=True,
    )

    assert crops["objects"] == []
    assert crops["skipped_incomplete_labels"] == [1]


def test_masked_crop_drops_objects_touching_image_boundary():
    image = np.ones((20, 20), dtype=np.uint8)
    masks = np.zeros((20, 20), dtype=np.int32)
    masks[0:5, 8:12] = 1

    crops = extract_object_crops(
        image=image,
        masks=masks,
        tile_id=["R0", 0, 0],
        crop_size_px=12,
        mask=True,
        drop_incomplete=True,
    )

    assert crops["objects"] == []
    assert crops["skipped_incomplete_labels"] == [1]


def test_crop_size_must_contain_the_whole_object():
    image = np.ones((30, 30), dtype=np.uint8)
    masks = np.zeros((30, 30), dtype=np.int32)
    masks[10:20, 10:24] = 1

    crops = extract_object_crops(
        image=image,
        masks=masks,
        tile_id=["R0", 0, 0],
        crop_size_px=8,
        mask=True,
        drop_incomplete=True,
    )

    assert crops["objects"] == []
    assert crops["skipped_incomplete_labels"] == [1]


def test_masked_crop_zeroes_context_pixels(tmp_path):
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(image_path),
        "metadata": {"verbose": 0},
    }
    pipeline_data = detect_objects.run(pipeline_data, {"model": _StubCellposeModel()})
    crops = extract_object_crops(
        image=pipeline_data["detect_objects"]["image_2d"],
        masks=pipeline_data["detect_objects"]["masks"],
        tile_id=pipeline_data["input"]["tile_id"],
        crop_size_px=10,
        mask=True,
    )
    obj = crops["objects"][0]

    crop = obj["crop_image"]
    mask = obj["crop_mask"].astype(bool)
    assert crop[mask].max() > 0
    assert np.all(crop[~mask] == 0)


def test_deep_crop_geometry_comes_from_step_params(tmp_path):
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(
            image_path,
            backend="mock",
            embedding_dim=6,
            crop_size_px=9,
            mask=True,
        ),
        "metadata": {"verbose": 0},
    }
    state = {"model": _StubCellposeModel()}
    pipeline_data = detect_objects.run(pipeline_data, state)
    pipeline_data = extract_classical_features.run(pipeline_data, {})
    pipeline_data = extract_deep_features.run(
        pipeline_data,
        {},
        crop_size_px=28,
        mask=False,
    )
    result = build_object_table.run(pipeline_data, {})["object_analysis"]
    props = result["objects"]["properties"]

    assert props["label"] == [2]
    assert props["crop_height_px"] == [28]
    assert props["crop_width_px"] == [28]
    assert props["crop_complete"] == [True]
    assert result["objects"]["embeddings"]["crop_policy"] == {
        "crop_size_px": 28,
        "mask": False,
        "drop_incomplete": True,
        "align_orientation": False,
        "min_eccentricity_to_align": 0.4,
        "orientation_target_deg": 45.0,
    }


def test_deep_step_publishes_orientation_alignment_columns(tmp_path):
    import tifffile

    image_path = tmp_path / "elongated.ome.tiff"
    image = np.ones((96, 96), dtype=np.uint8)
    masks = np.zeros((96, 96), dtype=np.int32)
    masks[46:50, 28:68] = 1
    tifffile.imwrite(image_path, image)
    pipeline_data = {
        "input": _payload(
            image_path,
            backend="mock",
            embedding_dim=6,
            source_image_size_px=[96, 96],
        ),
        "metadata": {"verbose": 0},
        "detect_objects": {
            "image_2d": image,
            "image": image,
            "masks": masks,
            "image_size_px": [96, 96],
        },
        "extract_features": {
            "properties": {
                "label": [1],
                "centroid-0": [47.5],
                "centroid-1": [47.5],
                "bbox-0": [46],
                "bbox-1": [28],
                "bbox-2": [50],
                "bbox-3": [68],
                "area": [160],
                "intensity_mean": [1.0],
                "eccentricity": [0.99],
            }
        },
    }

    pipeline_data = extract_deep_features.run(
        pipeline_data,
        {},
        backend="mock",
        embedding_dim=6,
        crop_size_px=48,
        mask=True,
        align_orientation=True,
        min_eccentricity_to_align=0.0,
    )
    result = build_object_table.run(pipeline_data, {})["object_analysis"]
    props = result["objects"]["properties"]

    assert props["label"] == [1]
    assert props["crop_aligned_orientation"] == [True]
    assert props["object_fits_crop"] == [True]
    assert props["crop_rotation_deg"][0] == pytest.approx(-45.0, abs=1.0)
    assert props["crop_eccentricity"][0] > 0.8
    assert props["crop_oriented_extent_px"][0] < 48
    assert result["objects"]["embeddings"]["crop_policy"]["align_orientation"] is True


def test_mock_deep_features_merge_into_object_table(tmp_path):
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(image_path, backend="mock", embedding_dim=6),
        "metadata": {"verbose": 0},
    }
    state = {"model": _StubCellposeModel()}
    pipeline_data = detect_objects.run(pipeline_data, state)
    pipeline_data = extract_classical_features.run(pipeline_data, {})
    pipeline_data = extract_deep_features.run(pipeline_data, {}, crop_size_px=12)
    result = build_object_table.run(pipeline_data, {})["object_analysis"]

    embeddings = result["objects"]["embeddings"]
    assert embeddings["backend"] == "mock"
    assert embeddings["label"] == result["objects"]["properties"]["label"]
    assert len(embeddings["vectors"]) == 2
    assert len(embeddings["vectors"][0]) == 6


def test_embedding_row_alignment_is_validated(tmp_path):
    image_path = _write_synthetic_tile(tmp_path)
    pipeline_data = {
        "input": _payload(image_path),
        "metadata": {"verbose": 0},
    }
    state = {"model": _StubCellposeModel()}
    pipeline_data = detect_objects.run(pipeline_data, state)
    pipeline_data = extract_classical_features.run(pipeline_data, {})
    pipeline_data["extract_deep_features"] = {
        "embeddings": {
            "label": [2, 1],
            "vectors": [[1.0, 0.0], [0.0, 1.0]],
            "model": "bad",
            "backend": "mock",
        }
    }

    with pytest.raises(ValueError, match="embeddings.label"):
        build_object_table.run(pipeline_data, {})


def test_dino_rgb_conversion_handles_fewer_than_three_channels():
    gray = np.full((6, 7), 11, dtype=np.uint8)
    one = np.full((6, 7, 1), 13, dtype=np.uint8)
    two = np.zeros((6, 7, 2), dtype=np.uint8)
    two[..., 0] = 17
    two[..., 1] = 19

    gray_rgb = extract_deep_features._as_rgb(gray)
    one_rgb = extract_deep_features._as_rgb(one)
    two_rgb = extract_deep_features._as_rgb(two)

    assert gray_rgb.shape == (6, 7, 3)
    assert one_rgb.shape == (6, 7, 3)
    assert two_rgb.shape == (6, 7, 3)
    assert np.all(gray_rgb[..., 0] == 11)
    assert np.all(one_rgb[..., 2] == 13)
    assert np.all(two_rgb[..., 0] == 17)
    assert np.all(two_rgb[..., 1] == 19)
    assert np.all(two_rgb[..., 2] == 18)


def test_dino_default_device_prefers_cuda_then_mps_then_cpu():
    class _Cuda:
        def __init__(self, available):
            self._available = available

        def is_available(self):
            return self._available

    class _Mps:
        def __init__(self, available):
            self._available = available

        def is_available(self):
            return self._available

    class _Backends:
        def __init__(self, mps_available):
            self.mps = _Mps(mps_available)

    class _Torch:
        def __init__(self, cuda_available, mps_available):
            self.cuda = _Cuda(cuda_available)
            self.backends = _Backends(mps_available)

    assert extract_deep_features._default_torch_device(_Torch(True, True)) == "cuda"
    assert extract_deep_features._default_torch_device(_Torch(False, True)) == "mps"
    assert extract_deep_features._default_torch_device(_Torch(False, False)) == "cpu"


def test_dino_two_channel_uint16_rgb_chain_scales_by_dtype():
    image = np.zeros((6, 7, 2), dtype=np.uint16)
    image[..., 0] = 12000
    image[..., 1] = 24000

    rgb = extract_deep_features._as_rgb(image)
    scaled = extract_deep_features._raw_image_to_float01(rgb)

    assert rgb.dtype == np.uint16
    assert scaled.shape == (6, 7, 3)
    assert scaled[..., 0].mean() == pytest.approx(12000 / 65535)
    assert scaled[..., 1].mean() == pytest.approx(24000 / 65535)
    assert scaled[..., 2].mean() == pytest.approx(18000 / 65535)


def test_dino_raw_integer_conversion_preserves_relative_brightness():
    image = np.asarray(
        [
            [[0, 25, 50], [50, 75, 100]],
            [[100, 125, 150], [150, 175, 200]],
        ],
        dtype=np.uint8,
    )

    scaled = extract_deep_features._raw_image_to_float01(image)

    assert scaled[0, 0, 0] == pytest.approx(0.0)
    assert scaled[0, 1, 0] == pytest.approx(50 / 255)
    assert scaled[1, 1, 2] == pytest.approx(200 / 255)


def test_dino_shared_intensity_scale_preserves_relative_brightness():
    image = np.asarray(
        [
            [[100, 200, 300], [500, 600, 700]],
            [[900, 1000, 1100], [1300, 1400, 1500]],
        ],
        dtype=np.uint16,
    )
    scale = {
        "mode": "foreground_run",
        "foreground": True,
        "lo": [100, 200, 300],
        "hi": [1100, 1200, 1300],
    }

    scaled = extract_deep_features._raw_image_to_float01(
        image,
        intensity_scale=scale,
    )

    assert scaled[0, 0, 0] == pytest.approx(0.0)
    assert scaled[0, 0, 1] == pytest.approx(0.0)
    assert scaled[0, 0, 2] == pytest.approx(0.0)
    assert scaled[0, 1, 0] == pytest.approx(0.4)
    assert scaled[0, 1, 1] == pytest.approx(0.4)
    assert scaled[0, 1, 2] == pytest.approx(0.4)
    assert scaled[1, 1, 0] == pytest.approx(1.0)
    assert scaled[1, 1, 1] == pytest.approx(1.0)
    assert scaled[1, 1, 2] == pytest.approx(1.0)


def test_foreground_intensity_scale_uses_accepted_object_pixels_only():
    image = np.zeros((4, 4, 3), dtype=np.uint16)
    masks = np.zeros((4, 4), dtype=np.int32)

    masks[0, 0] = 1
    image[0, 0] = [1, 2, 3]

    masks[1:3, 1:3] = 2
    image[1, 1] = [100, 200, 300]
    image[1, 2] = [150, 250, 350]
    image[2, 1] = [200, 300, 400]
    image[2, 2] = [250, 350, 450]

    field = {"image": image, "tile_id": ("T", 0), "pixel_um": 1.0}
    scale = compute_foreground_intensity_scale(
        [field],
        masks_by_tile={("T", 0): masks},
        min_area_px=2,
        percentiles=(0, 100),
    )

    assert scale["foreground"] is True
    assert scale["lo"] == [100.0, 200.0, 300.0]
    assert scale["hi"] == [250.0, 350.0, 450.0]


def test_dino_float_crops_must_be_preprocessed_to_unit_range():
    image = np.full((4, 5, 3), 2.0, dtype=np.float32)

    with pytest.raises(ValueError, match="preprocessing"):
        extract_deep_features._raw_image_to_float01(image)


def test_dino_rgb_conversion_rejects_non_crop_shapes():
    channel_first = np.zeros((2, 6, 7), dtype=np.uint8)
    with pytest.raises(ValueError, match="2D crop"):
        extract_deep_features._as_rgb(channel_first)


def test_dino_input_size_validation_uses_backend_patch_size():
    extract_deep_features._validate_input_size_px(518, backend="dinov2")
    extract_deep_features._validate_input_size_px(512, backend="dinov3")

    with pytest.raises(ValueError, match="multiple.*14"):
        extract_deep_features._validate_input_size_px(512, backend="dinov2")
    with pytest.raises(ValueError, match="multiple.*16"):
        extract_deep_features._validate_input_size_px(518, backend="dinov3")


def test_dinov2_local_weight_cache_bridges_v2_folder(tmp_path):
    source_dir = tmp_path / "v2"
    source_dir.mkdir()
    source = source_dir / "dinov2_vitb14_pretrain.pth"
    source.write_bytes(b"weights")

    target = extract_deep_features._prepare_dinov2_local_checkpoint(
        "dinov2_vitb14",
        tmp_path,
    )

    assert target == tmp_path / "dinov2" / "torch_hub" / "checkpoints" / source.name
    assert target.exists()
    assert target.read_bytes() == b"weights"


def test_dinov3_local_weight_resolution_supports_cache_layout(tmp_path):
    weights_dir = tmp_path / "v3"
    weights_dir.mkdir()
    weights = weights_dir / "dinov3_vitb16_pretrain_lvd1689m-73cec8be.pth"
    weights.write_bytes(b"weights")
    (weights_dir / "dinov3_vitb16_pretrain_lvd1689m-73cec8be.pth.part").write_bytes(b"partial")

    resolved = extract_deep_features._resolve_dinov3_weights("dinov3_vitb16", tmp_path)

    assert resolved == weights


def test_dinov3_local_weights_bypass_hub_url_loader(tmp_path, monkeypatch):
    weights = tmp_path / "dinov3_vits16_pretrain_lvd1689m-08c60483.pth"
    weights.write_bytes(b"weights")
    calls = {}

    class _Model:
        def load_state_dict(self, state_dict, *, strict):
            calls["state_dict"] = state_dict
            calls["strict"] = strict

    class _Hub:
        def load(self, repo, model_name, **kwargs):
            calls["hub"] = (repo, model_name, kwargs)
            return _Model()

    class _Torch:
        hub = _Hub()

    monkeypatch.setattr(
        extract_deep_features,
        "_load_torch_state_dict",
        lambda torch, path: {"weight": "loaded"},
    )

    model = extract_deep_features._load_dinov3_torch_hub_model(
        _Torch,
        "dinov3_vits16",
        weights,
    )

    assert isinstance(model, _Model)
    assert calls["hub"] == (
        "facebookresearch/dinov3",
        "dinov3_vits16",
        {"pretrained": False},
    )
    assert calls["state_dict"] == {"weight": "loaded"}
    assert calls["strict"] is True


def test_torch_state_dict_loader_unwraps_nested_module_prefix(tmp_path):
    weights = tmp_path / "weights.pth"

    class _Torch:
        @staticmethod
        def load(path, **kwargs):
            assert path == str(weights)
            assert kwargs["map_location"] == "cpu"
            assert kwargs["weights_only"] is True
            return {
                "state_dict": {
                    "module.cls_token": "a",
                    "module.patch_embed.proj.weight": "b",
                }
            }

    state = extract_deep_features._load_torch_state_dict(_Torch, weights)

    assert state == {
        "cls_token": "a",
        "patch_embed.proj.weight": "b",
    }


def test_dinov3_huggingface_name_maps_to_hub_name():
    assert (
        extract_deep_features._dinov3_hub_name("facebook/dinov3-vitb16-pretrain-lvd1689m")
        == "dinov3_vitb16"
    )


def test_forward_dinov3_prefers_pooler_output():
    pooled = np.asarray([[1.0, 2.0, 3.0]])

    class _Output:
        pooler_output = pooled

    class _Model:
        def __call__(self, pixel_values):
            return _Output()

    out = extract_deep_features._forward_dinov3(_Model(), batch="unused", torch=None)

    assert out is pooled


def test_forward_dinov3_falls_back_to_cls_token():
    hidden = np.arange(2 * 5 * 3, dtype=float).reshape(2, 5, 3)

    class _Output:
        pooler_output = None
        last_hidden_state = hidden

    class _Model:
        def __call__(self, pixel_values):
            return _Output()

    out = extract_deep_features._forward_dinov3(_Model(), batch="unused", torch=None)

    np.testing.assert_array_equal(out, hidden[:, 0, :])


def test_extract_deep_features_accepts_dinov3_backend(monkeypatch):
    image = np.zeros((24, 24, 3), dtype=np.uint8)
    image[8:16, 8:16] = 180
    masks = np.zeros((24, 24), dtype=np.int32)
    masks[8:16, 8:16] = 1
    input_intensity_scale = {
        "mode": "foreground_run",
        "foreground": True,
        "lo": [10, 20, 30],
        "hi": [100, 200, 300],
    }

    def _fake_dinov3(
        objects,
        state,
        *,
        model_name,
        input_size_px,
        batch_size,
        device,
        model_cache_dir,
        input_intensity_scale,
    ):
        assert len(objects) == 1
        assert model_name == "dinov3_vits16"
        assert input_size_px == 512
        assert batch_size == 4
        assert device is None
        assert model_cache_dir == "Z:/cache/DINO"
        assert input_intensity_scale["mode"] == "foreground_run"
        assert input_intensity_scale["lo"].tolist() == [10.0, 20.0, 30.0]
        assert input_intensity_scale["hi"].tolist() == [100.0, 200.0, 300.0]
        return [[1.0, 0.0, 0.0]]

    monkeypatch.setattr(extract_deep_features, "_dinov3_embeddings", _fake_dinov3)
    pipeline_data = {
        "input": {"tile_id": ["T", 0, 0]},
        "metadata": {"verbose": 0},
        "detect_objects": {
            "image": image,
            "image_2d": image[..., 0],
            "masks": masks,
        },
    }

    out = extract_deep_features.run(
        pipeline_data,
        {},
        backend="dinov3",
        model_name="dinov3_vits16",
        model_cache_dir="Z:/cache/DINO",
        input_size_px=512,
        input_intensity_scale=input_intensity_scale,
        batch_size=4,
        crop_size_px=12,
        drop_incomplete_crops=True,
    )

    embeddings = out["extract_deep_features"]["embeddings"]
    assert embeddings["backend"] == "dinov3"
    assert embeddings["model"] == "dinov3_vits16"
    assert embeddings["input_size_px"] == 512
    assert embeddings["batch_size"] == 4
    assert embeddings["patch_size_px"] == 16
    assert embeddings["model_cache_dir"] == "Z:/cache/DINO"
    assert embeddings["input_intensity_scale"] == {
        "mode": "foreground_run",
        "foreground": True,
        "lo": [10.0, 20.0, 30.0],
        "hi": [100.0, 200.0, 300.0],
    }
    assert embeddings["vectors"] == [[1.0, 0.0, 0.0]]


def test_yaml_registers_classical_and_deep():
    from engine import Engine

    with Engine() as engine:
        engine.register("object_analysis", str(CLASSICAL_YAML))
        engine.register("object_analysis_deep", str(DEEP_YAML))
        engine.register("object_detection", str(DETECTION_YAML))
        engine.register("object_features_deep", str(FEATURES_DEEP_YAML))
        classical = engine.status("object_analysis")
        deep = engine.status("object_analysis_deep")
        detection = engine.status("object_detection")
        features = engine.status("object_features_deep")

    assert classical["completed"] == 0
    assert classical["failed"] == 0
    assert deep["completed"] == 0
    assert deep["failed"] == 0
    assert detection["completed"] == 0
    assert detection["failed"] == 0
    assert features["completed"] == 0
    assert features["failed"] == 0


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


@pytest.mark.cellpose
@pytest.mark.deep
@pytest.mark.pooch
@pytest.mark.slow
def test_real_dinov2_embedding_end_to_end(tmp_path):
    image_path, image = _write_immunohistochemistry_tile(tmp_path)

    result = _run_engine_workflow(
        "object_analysis_real_deep",
        DEEP_YAML,
        _payload(
            image_path,
            backend="dinov2",
            model_name="dinov2_vitb14",
            input_size_px=224,
            batch_size=1,
            gpu=True,
            source_image_size_px=[int(image.shape[1]), int(image.shape[0])],
        ),
        timeout=240,
    )

    tile = validate_tile_detection(result["object_analysis"])
    embeddings = tile["objects"]["embeddings"]
    assert embeddings["backend"] == "dinov2"
    assert embeddings["label"] == tile["objects"]["properties"]["label"]
    assert len(embeddings["vectors"]) == tile["objects"]["n_objects"]
    assert len(embeddings["vectors"][0]) > 100


class _StubCellposeModel:
    def eval(self, x, channel_axis=None, **kwargs):
        masks = np.zeros(x.shape[:2], dtype=np.int32)
        masks[5:11, 6:12] = 1
        masks[20:30, 25:35] = 2
        return masks, None, None


class _ShapeAgnosticCellposeModel:
    def eval(self, x, channel_axis=None, **kwargs):
        return np.zeros(x.shape[:2], dtype=np.int32), None, None

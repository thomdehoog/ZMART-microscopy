from __future__ import annotations

from pathlib import Path

import build_object_table
import measure_objects
import numpy as np
import pytest
import segment_cellpose
import segment_watershed
from helpers import fresh_output, load_step
from segment_cellpose import to_builtin

read_images = load_step("object_analysis", "read_images")
validate_tile_detection = build_object_table._validated

WORKFLOW = Path(__file__).resolve().parents[1]
CELLPOSE_YAML = WORKFLOW / "pipelines" / "object_analysis_cellpose.yaml"
WATERSHED_YAML = WORKFLOW / "pipelines" / "object_analysis_watershed.yaml"


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
    tifffile.imwrite(path, np.moveaxis(image, -1, 0), metadata={"axes": "CYX"})
    return path, image


def _payload(image_path: Path, **extra):
    payload = {
        "image_path": str(image_path),
        "tile_id": ["R0", 3, 7],
        "tile_stage_xy_um": [1000.0, 2000.0],
        "tile_z_um": 250.0,
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
    pipeline_data = read_images.run(pipeline_data, {})
    pipeline_data = segment_cellpose.run(pipeline_data, state)
    pipeline_data = measure_objects.run(pipeline_data, {})
    return build_object_table.run(pipeline_data, {})


def _run_engine_workflow(name: str, yaml_path: Path, payload: dict, timeout=180):
    import time

    from zmart_analysis import Engine

    with Engine() as engine:
        engine.register(name, str(yaml_path), fresh_output())
        job = engine.submit(pipeline=name, data=payload)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            entry = engine.status(name)[job]
            if entry["state"] == "done":
                return entry["output"]
            if entry["state"] == "failed":
                raise AssertionError(f"{entry['step']}: {entry['error']}")
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
    assert props["stage_x_um"] == pytest.approx([970.0, 1012.0])
    assert props["stage_y_um"] == pytest.approx([1964.0, 2015.0])
    assert "centroid-0" not in props
    assert "bbox-0" not in props
    assert "measure_objects" not in result
    assert "read_images" not in result
    assert "masks" not in result["segment_cellpose"]
    assert result["segment_cellpose"]["detector_params"]["device"] == "cpu"


def test_detection_checkpoint_hash_ignores_runtime_and_area_filter():
    segmentation_params_hash = segment_cellpose._segmentation_hash
    base = {
        "channels": None,
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
    assert segmentation_params_hash(base | {"unused_legacy_key": 1.0}) == (
        segmentation_params_hash(base | {"unused_legacy_key": None})
    )


def test_the_segmentation_hash_of_known_settings_is_fixed():
    """Checkpoints written before and after a code change must agree on what made their masks."""
    settings = {
        "z_selection": "max",
        "channels": [0],
        "method": "fast",
        "threshold": 100.0,
        "cellprob_threshold": None,
        "flow_threshold": None,
        "niter": None,
        "diameter": 14,
        "segmentation_binning": None,
    }
    assert segment_cellpose._segmentation_hash(settings) == (
        "966544120468c6857a2ff30d6d2f58e9bd7da035ddc09b38b4eee2e8536be7f7"
    )


def test_area_filter_rejects_ambiguous_pixel_and_diameter_thresholds():
    with pytest.raises(ValueError, match="not both"):
        segment_cellpose._area_filter_params(
            {"source_pixel_size_um": [0.5, 0.5]},
            {"min_area_px": 10, "min_equivalent_diameter_um": 5.0},
        )


def test_the_pipelines_register(tmp_path):
    """Every shipped YAML parses and resolves its steps."""
    from zmart_analysis import Engine

    engine = Engine()
    try:
        engine.register("cellpose", str(CELLPOSE_YAML), fresh_output())
        engine.register("watershed", str(WATERSHED_YAML), fresh_output())
        placed = {
            "cellpose": engine.pipelines["cellpose"].step_settings["segment_cellpose"][
                "environment"
            ],
            "watershed": engine.pipelines["watershed"].step_settings["segment_watershed"][
                "environment"
            ],
        }
    finally:
        engine.shutdown()
    # Each detector's step file names its own environment: the watershed
    # needs no torch, so it never starts the Cellpose worker.
    assert placed["cellpose"] == "ZMART--object_analysis--cellpose"
    assert placed["watershed"] == "ZMART--object_analysis--classical"


def test_both_pipelines_read_first_and_answer_under_the_same_name():
    """Whoever reads the table reads ``pipeline_data["object_analysis"]``."""
    import yaml

    for path, segmenter in (
        (CELLPOSE_YAML, "segment_cellpose"),
        (WATERSHED_YAML, "segment_watershed"),
    ):
        steps = [next(iter(step)) for step in yaml.safe_load(path.read_text())["object_analysis"]]
        assert steps == ["read_images", segmenter, "measure_objects", "build_object_table"]


def test_the_watershed_step_finds_the_four_blobs(tmp_path):
    """The watershed's detection carries method "fast" and the same record as Cellpose's."""
    import tifffile

    yy, xx = np.mgrid[0:96, 0:96]
    plane = np.zeros((96, 96))
    for cy, cx in [(24, 24), (24, 72), (72, 24), (72, 72)]:
        plane += 1500.0 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 6.0**2))
    path = tmp_path / "field.tif"
    tifffile.imwrite(path, plane.astype(np.uint16))
    data = {
        "input": _payload(path, source_image_size_px=[96, 96]),
        "metadata": {"verbose": 0},
    }
    data = read_images.run(data, {})
    out = segment_watershed.run(data, {}, threshold=100, diameter=12, output_dir=str(tmp_path))
    detection = out["segment_watershed"]
    assert detection["detector_params"]["method"] == "fast"
    assert detection["segmentation_params"]["method"] == "fast"
    assert detection["n_objects"] == 4
    assert (tmp_path / "tiles" / "field" / "detection_checkpoint.json").exists()


def test_the_fast_pipeline_leaves_out_the_per_object_texture_crops():
    """glrlm, lbp and fft each loop over every object's crop in Python and
    together were 4.5 s of a 5.8 s features step on a 488-object mock tile;
    everything else was 1.5 s. Fast means without them."""
    import yaml

    fast = yaml.safe_load(WATERSHED_YAML.read_text())
    extras, _unknown = measure_objects._expand_extras(
        fast["object_analysis"][2]["measure_objects"]["extras"]
    )
    assert not extras & {"glrlm", "lbp", "fft"}
    assert extras == set(measure_objects.EXTRAS) - {"glrlm", "lbp", "fft"}


def _used_gpu(root: Path) -> bool:
    """Whether Cellpose ran on the GPU, as the detection step wrote it down beside its masks."""
    import json

    checkpoint = next(root.rglob("detection_checkpoint.json"))
    return json.loads(checkpoint.read_text())["detector_params"]["used_gpu"]


@pytest.mark.cellpose
@pytest.mark.pooch
@pytest.mark.slow
def test_real_cellpose_object_analysis_end_to_end(tmp_path, cellpose_device):
    image_path, image = _write_immunohistochemistry_tile(tmp_path)

    result = _run_engine_workflow(
        "object_analysis_real_cellpose",
        CELLPOSE_YAML,
        _payload(
            image_path,
            tile_id=["IHC", 0, 0],
            tile_stage_xy_um=[10000.0, 15000.0],
            source_pixel_size_um=[0.5, 0.5],
            source_image_size_px=[int(image.shape[1]), int(image.shape[0])],
            image_to_stage=[[0.0, -1.0], [1.0, 0.0]],
            channels=None,
            gpu=True,
            output_dir=str(tmp_path / "analysis"),
        ),
    )
    tile = validate_tile_detection(result["object_analysis"])

    # Asked for the GPU, it must be used whenever the environment has one.
    assert _used_gpu(tmp_path) is (cellpose_device == "cuda")
    assert tile["objects"]["n_objects"] > 0
    assert tile["objects"]["properties"]["object_id"][0].startswith("IHC_r000_c000_obj")
    assert all(isinstance(value, float) for value in tile["objects"]["properties"]["stage_x_um"])


@pytest.mark.cellpose
@pytest.mark.pooch
@pytest.mark.slow
def test_real_cpsam_multichannel_immunohistochemistry_end_to_end(tmp_path, cellpose_device):
    image_path, image = _write_immunohistochemistry_tile(tmp_path)

    result = _run_engine_workflow(
        "object_analysis_real_cpsam_multichannel",
        CELLPOSE_YAML,
        _payload(
            image_path,
            tile_id=["IHC", 0, 0],
            tile_stage_xy_um=[5000.0, 6000.0],
            source_pixel_size_um=[0.5, 0.5],
            source_image_size_px=[int(image.shape[1]), int(image.shape[0])],
            image_to_stage=[[1.0, 0.0], [0.0, 1.0]],
            channels=None,
            gpu=True,
            output_dir=str(tmp_path / "analysis"),
        ),
        timeout=240,
    )
    tile = validate_tile_detection(result["object_analysis"])
    props = tile["objects"]["properties"]

    assert _used_gpu(tmp_path) is (cellpose_device == "cuda")
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


def test_a_single_object_field_survives_to_builtin_and_the_table():
    """A one-element numpy column must stay a list.

    ``.item()`` answers on a one-element array as happily as on a scalar,
    and taking it collapsed every column of a single-object field to a bare
    number -- ``len()`` then died on an int at the top of the table step.
    Dense test fields never showed it; the first field with exactly one
    cell killed a whole nine-field run.
    """
    assert to_builtin(np.array([5])) == [5]
    assert to_builtin(np.int32(5)) == 5
    assert to_builtin(np.array([2.0])) == [2.0]

    props = {
        name: np.array([value])
        for name, value in [
            ("label", 1),
            ("centroid-0", 5.0),
            ("centroid-1", 6.0),
            ("bbox-0", 1),
            ("bbox-1", 2),
            ("bbox-2", 9),
            ("bbox-3", 9),
            ("area", 64.0),
            ("intensity_mean", 10.0),
            ("eccentricity", 0.5),
        ]
    }
    data = {
        "metadata": {},
        "input": {
            "tile_id": ["overview", 2, 0],
            "tile_stage_xy_um": [0.0, 0.0],
            "source_pixel_size_um": [4.0, 4.0],
            "source_image_size_px": [64, 64],
            "image_to_stage": [[1, 0], [0, 1]],
        },
        "read_images": {"image_size_px": [64, 64]},
        "measure_objects": {"properties": props},
    }
    out = build_object_table.run(data, {})
    assert out["object_analysis"]["objects"]["n_objects"] == 1
    assert out["object_analysis"]["objects"]["properties"]["label"] == [1]


def test_a_pixel_is_placed_at_its_centre_on_the_stage():
    """A centroid at pixel index i is the centre of pixel i.

    The tile's stage position is the centre of the image, so the first and the
    last pixel lie symmetrically about it: in a 10-pixel row of 2 um pixels
    centred at x = 100, pixel 0 is centred at 91 and pixel 9 at 109. Counting
    from the pixel's corner put every object half a pixel low (90 and 108).
    """
    geometry = {
        "source_image_size_px": [10, 10],
        "source_pixel_size_um": [2.0, 2.0],
        "tile_stage_xy_um": [100.0, 50.0],
        "image_to_stage": [[1.0, 0.0], [0.0, 1.0]],
    }
    assert build_object_table._stage_position(0, 0, geometry) == pytest.approx((91.0, 41.0))
    assert build_object_table._stage_position(9, 9, geometry) == pytest.approx((109.0, 59.0))
    assert build_object_table._stage_position(4.5, 4.5, geometry) == pytest.approx((100.0, 50.0))


def _write_synthetic_ome_zarr(tmp_path, centre_xy_um, pixel_um):
    """The synthetic tile as an OME-Zarr image, centred on the stage at ``centre_xy_um``.

    OME-NGFF places an image by the centre of its first pixel (the translation)
    and sizes it by the pixel size (the scale), the way the drivers write it.
    """
    import ngio

    image = np.zeros((40, 48), dtype=np.uint8)
    image[5:11, 6:12] = 80
    image[20:30, 25:35] = 160
    ny, nx = image.shape
    first_pixel_x = centre_xy_um[0] - (nx - 1) * pixel_um / 2
    first_pixel_y = centre_xy_um[1] - (ny - 1) * pixel_um / 2
    path = tmp_path / "overview0.ome.zarr"
    ngio.create_ome_zarr_from_array(
        str(path),
        image,
        pixelsize=pixel_um,
        axes_names=("y", "x"),
        translation=(first_pixel_y, first_pixel_x),
        overwrite=True,
    )
    return path


def _run_classical_on(image_path, payload):
    pipeline_data = {
        "input": {"image_path": str(image_path), "gpu": False, **payload},
        "metadata": {"verbose": 0},
    }
    pipeline_data = read_images.run(pipeline_data, {})
    pipeline_data = segment_cellpose.run(pipeline_data, {"model": _StubCellposeModel()})
    pipeline_data = measure_objects.run(pipeline_data, {})
    return build_object_table.run(pipeline_data, {})


def test_an_ome_zarr_image_alone_is_enough(tmp_path):
    """Given only the image, the table takes where and how big from its OME-NGFF metadata.

    The driver writes the pixel size, the position and an image already lined
    up with the stage; nothing of that has to be said again when submitting.
    """
    path = _write_synthetic_ome_zarr(tmp_path, centre_xy_um=(100.0, 50.0), pixel_um=2.0)

    tile = _run_classical_on(path, {})["object_analysis"]

    assert tile["geometry"]["tile_stage_xy_um"] == pytest.approx([100.0, 50.0])
    assert tile["geometry"]["source_pixel_size_um"] == pytest.approx([2.0, 2.0])
    assert tile["geometry"]["image_to_stage"] == [[1.0, 0.0], [0.0, 1.0]]
    assert tile["geometry"]["tile_id"] == ["overview0"]
    assert tile["objects"]["properties"]["stage_x_um"] == pytest.approx([70.0, 112.0])
    assert tile["objects"]["properties"]["stage_y_um"] == pytest.approx([26.0, 60.0])


def test_what_is_given_wins_over_the_image_metadata(tmp_path):
    """A caller that knows better (the interface's scan) still says where the tile was."""
    path = _write_synthetic_ome_zarr(tmp_path, centre_xy_um=(100.0, 50.0), pixel_um=2.0)

    tile = _run_classical_on(path, {"tile_stage_xy_um": [0.0, 0.0], "tile_id": ["R0", 3, 7]})[
        "object_analysis"
    ]

    assert tile["geometry"]["tile_stage_xy_um"] == [0.0, 0.0]
    assert tile["geometry"]["tile_id"] == ["R0", 3, 7]


def test_a_tiff_without_a_position_says_what_is_missing(tmp_path):
    """A TIFF records no placement the analysis can trust, so it must be told where the tile was."""
    path = _write_synthetic_tile(tmp_path)

    with pytest.raises(ValueError, match="tile_stage_xy_um"):
        _run_classical_on(path, {"source_pixel_size_um": [2.0, 2.0]})

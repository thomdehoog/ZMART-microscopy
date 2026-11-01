"""The object-analysis pipelines on real microscopy, from scikit-image's sample data.

- ``human_mitosis``: a field of nuclei, one plane.
- ``cells3d``: a confocal stack of nuclei and membranes, read as a maximum projection.
- ``kidney``: a confocal stack of a kidney section, three colours.

The watershed runs in this process. Cellpose runs through the engine in its
own environment, and must use the GPU whenever that environment has one.
The samples are downloaded on first use and cached; without a network the
tests are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import build_object_table
import measure_objects
import numpy as np
import pytest
import segment_watershed
from helpers import fresh_output, load_step

read_images = load_step("object_analysis", "read_images")

CELLPOSE_YAML = Path(__file__).resolve().parents[1] / "pipelines" / "object_analysis_cellpose.yaml"

pytestmark = pytest.mark.pooch


def _sample(name):
    data = pytest.importorskip("skimage.data")
    try:
        return getattr(data, name)()
    except Exception as exc:
        pytest.skip(f"skimage sample {name} unavailable: {exc}")


def _tile(image_path, pixel_um, **extra):
    """The input the operator page sends for one tile."""
    return {
        "image_path": str(image_path),
        "tile_id": ["S", 0, 0],
        "tile_stage_xy_um": [0.0, 0.0],
        "source_pixel_size_um": [pixel_um, pixel_um],
        "image_to_stage": [[1.0, 0.0], [0.0, 1.0]],
        **extra,
    }


def _watershed(given, **settings):
    """The watershed pipeline in this process: the object table."""
    data = read_images.run({"input": given, "metadata": {"verbose": 0}}, {})
    data = segment_watershed.run(data, {}, **settings)
    data = measure_objects.run(data, {}, extras=["intensity", "neighbourhood", "morphology"])
    return build_object_table.run(data, {})["object_analysis"]


def _position(path, array_czyx, pixel_um, z_um):
    ngio = pytest.importorskip("ngio")
    ngio.create_ome_zarr_from_array(
        str(path),
        array_czyx[None],
        pixelsize=pixel_um,
        z_spacing=z_um,
        axes_names=("t", "c", "z", "y", "x"),
        levels=1,
        overwrite=True,
    )
    return path


@pytest.fixture(scope="module")
def mitosis(tmp_path_factory):
    import tifffile

    path = tmp_path_factory.mktemp("mitosis") / "data" / "mitosis.tif"
    path.parent.mkdir()
    tifffile.imwrite(path, _sample("human_mitosis"))
    return path


@pytest.fixture(scope="module")
def kidney(tmp_path_factory):
    stack = np.moveaxis(_sample("kidney"), -1, 0)
    return _position(tmp_path_factory.mktemp("kidney") / "kidney.zarr", stack, 0.5, 1.0)


@pytest.fixture(scope="module")
def cells3d(tmp_path_factory):
    stack = np.moveaxis(_sample("cells3d"), 1, 0)
    return _position(tmp_path_factory.mktemp("cells3d") / "cells3d.zarr", stack, 0.26, 0.29)


def test_the_watershed_finds_the_mitosis_nuclei(mitosis):
    table = _watershed(_tile(mitosis, 0.5), diameter=12, threshold=20)

    assert table["objects"]["n_objects"] == 387


def test_the_watershed_finds_the_kidney_nuclei_in_the_projection(kidney):
    given = _tile(kidney, 0.5, channels=[0], z_selection="max", extra_channel_indices=[1, 2])

    table = _watershed(given, diameter=10, threshold=100)

    props = table["objects"]["properties"]
    assert table["objects"]["n_objects"] == 2407
    # The other two colours are measured as well
    assert "intensity_mean_c1" in props and "intensity_mean_c2" in props


def test_the_watershed_finds_the_cells3d_nuclei(cells3d):
    given = _tile(cells3d, 0.26, channels=[1], z_selection="max")

    table = _watershed(given, diameter=70, threshold=2000)

    assert table["objects"]["n_objects"] == 22


def _cellpose(given):
    """The Cellpose pipeline through the engine; the table and the segmentation's record."""
    import time

    from zmart_analysis import Engine

    with Engine() as engine:
        engine.register("cellpose", str(CELLPOSE_YAML), fresh_output())
        job = engine.submit(pipeline="cellpose", data=given)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            entry = engine.status("cellpose")[job]
            if entry["state"] == "done":
                return entry["output"]
            if entry["state"] == "failed":
                raise AssertionError(f"{entry['step']}: {entry['error']}")
            time.sleep(0.2)
    raise AssertionError("timed out waiting for Cellpose")


@pytest.mark.cellpose
@pytest.mark.slow
def test_cellpose_finds_the_mitosis_nuclei_on_the_best_device(mitosis, cellpose_device):
    result = _cellpose(_tile(mitosis, 0.5, gpu=True))

    assert 300 <= result["object_analysis"]["objects"]["n_objects"] <= 360
    assert result["segment_cellpose"]["detector_params"]["device"] == cellpose_device
    record = json.loads(next(mitosis.parent.parent.rglob("detection_checkpoint.json")).read_text())
    assert record["detector_params"]["used_gpu"] is (cellpose_device == "cuda")


@pytest.mark.cellpose
@pytest.mark.slow
def test_cellpose_finds_the_kidney_nuclei_in_the_projection(kidney, cellpose_device):
    given = _tile(
        kidney, 0.5, channels=[0], z_selection="max", extra_channel_indices=[1, 2], gpu=True
    )

    result = _cellpose(given)

    assert 1950 <= result["object_analysis"]["objects"]["n_objects"] <= 2400
    assert result["segment_cellpose"]["detector_params"]["device"] == cellpose_device

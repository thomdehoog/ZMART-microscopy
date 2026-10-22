"""The pipeline, run through the ZMART analysis engine, on a small OME-Zarr image of two bright objects.

Needs the analysis environment: ``conda env create -f environments/classical.yml``.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from zmart_analysis import Engine
from zmart_analysis.conda import env_exists, get_conda_info

ANALYSIS = Path(__file__).resolve().parents[1]
PIPELINE = ANALYSIS / "pipelines" / "object_analysis_watershed.yaml"
ENVIRONMENT = "ZMART--target_acquisition_for_coders--classical"

pytestmark = pytest.mark.skipif(
    not env_exists(get_conda_info(), ENVIRONMENT),
    reason=f"{ENVIRONMENT} is not made yet: conda env create -f environments/classical.yml",
)


def _two_objects(folder: Path) -> Path:
    """A 64 x 64 OME-Zarr image with two bright squares on a dark field, saved as a ZMART
    driver saves one: in ``data``, with 1 um pixels, its first pixel at (68.5, 18.5) um,
    so the image is centred on (100, 50)."""
    zarr = pytest.importorskip("zarr")
    image = np.zeros((64, 64), dtype=np.uint16)
    image[10:20, 10:20] = 1000
    image[40:52, 30:42] = 2000
    path = folder / "data" / "two_objects.ome.zarr"
    group = zarr.open_group(path, mode="w", zarr_format=3)
    group.create_array("0", data=image[np.newaxis, np.newaxis, np.newaxis])
    space = {"type": "space", "unit": "micrometer"}
    group.attrs["ome"] = {
        "version": "0.5",
        "multiscales": [{
            "axes": [
                {"name": "t", "type": "time"},
                {"name": "c", "type": "channel"},
                {"name": "z", **space},
                {"name": "y", **space},
                {"name": "x", **space},
            ],
            "datasets": [{
                "path": "0",
                "coordinateTransformations": [
                    {"type": "scale", "scale": [1.0, 1.0, 1.0, 1.0, 1.0]},
                    {"type": "translation", "translation": [0.0, 0.0, 0.0, 18.5, 68.5]},
                ],
            }],
        }],
    }
    return path


def test_the_pipeline_finds_both_objects_and_places_them_on_the_stage(tmp_path):
    """What the notebook hands over: the path of the store the driver saved, nothing else."""
    image = _two_objects(tmp_path)

    with Engine() as analysis:
        analysis.register("detect_targets", str(PIPELINE), str(tmp_path / "analysis_output"))
        job = analysis.submit("detect_targets", {"image_path": str(image)})
        deadline = time.monotonic() + 300
        while analysis.status("detect_targets")[job]["state"] not in ("done", "failed"):
            assert time.monotonic() < deadline, "the analysis took longer than five minutes"
            time.sleep(0.2)
        entry = analysis.status("detect_targets")[job]

    assert entry["state"] == "done", entry.get("error")
    table = entry["output"]["object_analysis"]["objects"]["properties"]
    assert len(table["label"]) == 2
    # The squares' centres, at columns 14.5 and 35.5 and rows 14.5 and 45.5 of the image,
    # lie at x 68.5 + 14.5 = 83 and 68.5 + 35.5 = 104, and y 18.5 + 14.5 = 33 and 18.5 + 45.5 = 64.
    assert sorted(table["stage_x_um"]) == pytest.approx([83.0, 104.0])
    assert sorted(table["stage_y_um"]) == pytest.approx([33.0, 64.0])
    for column in ("intensity_cv", "eccentricity"):
        assert len(table[column]) == 2

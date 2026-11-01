"""The focus pipeline on real microscopy, from scikit-image's sample data.

- ``cells3d``: a confocal stack of nuclei, 60 planes 0.29 um apart.
- ``kidney``: a confocal stack of a kidney section, 16 planes.

The samples are downloaded on first use and cached; without a network the
tests are skipped.
"""

from __future__ import annotations

import numpy as np
import pytest
import score_focus
from helpers import load_step

read_images = load_step("focus", "read_images")

pytestmark = pytest.mark.pooch


def _sample(name):
    data = pytest.importorskip("skimage.data")
    try:
        return getattr(data, name)()
    except Exception as exc:
        pytest.skip(f"skimage sample {name} unavailable: {exc}")


def _through(step, given, **params):
    """read_images, then the step: the pipeline in this process."""
    reader = {key: params.pop(key) for key in ("channel", "level", "t") if key in params}
    data = read_images.run({"input": given, "metadata": {"verbose": 0}}, {}, **reader)
    return step.run(data, {}, **params)


@pytest.fixture(scope="module")
def cells3d_position(tmp_path_factory):
    """cells3d as one OME-Zarr position: membranes in channel 0, nuclei in channel 1."""
    ngio = pytest.importorskip("ngio")
    cells = _sample("cells3d")
    path = tmp_path_factory.mktemp("cells3d") / "cells3d.zarr"
    ngio.create_ome_zarr_from_array(
        str(path),
        np.moveaxis(cells, 1, 0)[None],
        pixelsize=0.26,
        z_spacing=0.29,
        axes_names=("t", "c", "z", "y", "x"),
        levels=1,
        overwrite=True,
    )
    return path


def test_the_nuclei_of_cells3d_are_sharpest_in_the_middle_of_the_stack(cells3d_position):
    found = _through(score_focus, {"image_path": str(cells3d_position)}, channel=1)["score_focus"]

    assert found["found"] is True
    assert found["n_planes"] == 60
    assert found["peak_z_um"] == pytest.approx(9.73, abs=0.3)


def test_the_same_stack_written_one_plane_per_file_focuses_the_same(cells3d_position, tmp_path):
    import tifffile

    cells = _sample("cells3d")
    paths = []
    for z in range(60):
        path = tmp_path / f"plane_{z:02d}.tif"
        tifffile.imwrite(path, cells[z, 1])
        paths.append(str(path))

    planes = _through(score_focus, {"image_paths": paths, "z_um": [0.29 * z for z in range(60)]})
    position = _through(score_focus, {"image_path": str(cells3d_position)}, channel=1)

    assert planes["score_focus"]["metrics"] == position["score_focus"]["metrics"]


def test_the_kidney_stack_is_sharpest_near_its_middle(tmp_path):
    ngio = pytest.importorskip("ngio")
    kidney = _sample("kidney")
    path = tmp_path / "kidney.zarr"
    ngio.create_ome_zarr_from_array(
        str(path),
        np.moveaxis(kidney, -1, 0)[None],
        pixelsize=0.5,
        z_spacing=1.0,
        axes_names=("t", "c", "z", "y", "x"),
        levels=1,
        overwrite=True,
    )

    found = _through(score_focus, {"image_path": str(path)}, channel=0, skip_ends=1)["score_focus"]

    assert found["found"] is True
    assert found["peak_z_um"] == pytest.approx(6.98, abs=0.5)

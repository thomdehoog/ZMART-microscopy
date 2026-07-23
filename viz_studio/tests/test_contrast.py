"""Choosing the intensity window a store is first displayed with.

The case that matters is the real one: 16-bit data whose signal occupies a few
hundred counts near the bottom of the range. Stretching the type's full range
there renders black, so these assert the window actually tracks the data.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import zarr
from contrast import display_window, shader_for_window
from demo_data import write_demo_zarr


def write_store(path, data: np.ndarray, omero: dict | None = None) -> str:
    """A minimal single-level OME-Zarr, enough for the window logic."""
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    array = group.create_array("0", shape=data.shape, chunks=data.shape, dtype=data.dtype)
    array[:] = data
    attrs = {
        "multiscales": [
            {
                "version": "0.4",
                "axes": [{"name": n, "type": "space"} for n in "zyx"],
                "datasets": [{"path": "0", "coordinateTransformations": []}],
            }
        ]
    }
    if omero is not None:
        attrs["omero"] = omero
    (path / ".zattrs").write_text(json.dumps(attrs), encoding="utf-8")
    return str(path)


def test_window_tracks_a_narrow_band_of_the_sixteen_bit_range(tmp_path):
    """Real mesoSPIM-like data: ~198 background, signal a few counts above."""
    rng = np.random.default_rng(0)
    data = rng.integers(198, 210, size=(8, 64, 64)).astype(np.uint16)
    window = display_window(write_store(tmp_path / "a.zarr", data))
    assert 195 <= window[0] <= 200
    assert 205 <= window[1] <= 212
    assert window[1] < 300, "a full-range window is what renders real data black"


def test_a_single_hot_pixel_does_not_stretch_the_window(tmp_path):
    """Min/max would blow the ramp out to 60000 and darken everything else."""
    data = np.full((8, 64, 64), 200, dtype=np.uint16)
    data[0, 0, 0] = 60000
    window = display_window(write_store(tmp_path / "b.zarr", data))
    assert window[1] < 1000


def test_a_declared_omero_window_is_honoured_over_measurement(tmp_path):
    data = np.full((4, 16, 16), 500, dtype=np.uint16)
    omero = {"channels": [{"window": {"start": 100.0, "end": 4000.0}}]}
    assert display_window(write_store(tmp_path / "c.zarr", data, omero)) == (100.0, 4000.0)


def test_the_demo_volume_uses_its_own_declared_window(tmp_path):
    store = write_demo_zarr(tmp_path / "demo.zarr")
    assert display_window(store) == (800.0, 20800.0)


def test_uniform_data_still_yields_a_usable_window(tmp_path):
    data = np.full((4, 16, 16), 42, dtype=np.uint16)
    low, high = display_window(write_store(tmp_path / "d.zarr", data))
    assert high > low


def test_an_unreadable_store_falls_back_to_the_full_range(tmp_path):
    assert display_window(tmp_path / "missing.zarr") == (0.0, 65535.0)


def test_volume_window_starts_far_above_the_background(tmp_path):
    """Sparse bright structure in a sea of background — the real 3-D case."""
    rng = np.random.default_rng(1)
    data = rng.integers(198, 205, size=(16, 64, 64)).astype(np.uint16)
    data[data.shape[0] // 2, ::16, ::16] = 5000  # a little real signal

    flat = display_window(write_store(tmp_path / "a.zarr", data))
    volume = display_window(write_store(tmp_path / "b.zarr", data), volumetric=True)
    assert volume[0] > flat[0], "a volume window must clear the background"
    assert volume[0] >= 204


def test_volume_window_ignores_a_declared_omero_window(tmp_path):
    """omero describes how to show a slice; obeying it in 3-D gives fog."""
    data = np.full((8, 32, 32), 300, dtype=np.uint16)
    omero = {"channels": [{"window": {"start": 0.0, "end": 65535.0}}]}
    store = write_store(tmp_path / "c.zarr", data, omero)
    assert display_window(store) == (0.0, 65535.0)
    assert display_window(store, volumetric=True) != (0.0, 65535.0)


def test_volumetric_shader_makes_intensity_drive_opacity(tmp_path):
    shader = shader_for_window(100.0, 500.0, (0.0, 1.0, 0.4), volumetric=True)
    assert "emitRGBA" in shader
    assert "float v = normalized();" in shader
    assert "v * opacity" in shader, "alpha must come from the intensity"
    assert "#uicontrol float opacity" in shader


def test_flat_shader_stays_opaque(tmp_path):
    shader = shader_for_window(100.0, 500.0, (0.0, 1.0, 0.4))
    assert "emitRGB(" in shader
    assert "emitRGBA" not in shader


def test_shader_stretches_the_given_window(tmp_path):
    shader = shader_for_window(198.0, 214.0)
    assert "range=[198, 214]" in shader
    assert "emitGrayscale(normalized())" in shader


@pytest.mark.parametrize("low,high", [(0.0, 1.0), (198.0, 214.0), (800.0, 20800.0)])
def test_shader_is_valid_glsl_shape_for_any_window(low, high):
    shader = shader_for_window(low, high)
    assert shader.startswith("#uicontrol invlerp normalized(range=[")
    assert shader.rstrip().endswith("}")

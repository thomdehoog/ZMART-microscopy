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
from contrast import HISTOGRAM_BINS, display_window, intensity_histogram, measure
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


def test_histogram_covers_every_sample_in_compact_bins(tmp_path):
    # Starting at 1, not 0: a voxel equal to the store's fill value is
    # excluded from the measurement by design (declared-but-unwritten ground
    # reads back as fill — see the generously-declared-room gate in
    # test_brightness_is_measured_honestly), and this test's own claim is
    # about bins covering the sample, not about that rule.
    data = np.arange(1, 8 * 16 * 16 + 1, dtype=np.uint16).reshape(8, 16, 16)
    histogram = intensity_histogram(write_store(tmp_path / "hist.zarr", data))
    assert histogram is not None
    assert len(histogram["counts"]) == HISTOGRAM_BINS
    assert sum(histogram["counts"]) == data.size
    assert histogram["high"] > histogram["low"]
    assert histogram["autoWindow"]["high"] > histogram["autoWindow"]["low"]


def test_histogram_range_resists_a_single_hot_pixel(tmp_path):
    data = np.full((8, 32, 32), 200, dtype=np.uint16)
    data[0, 0, 0] = 60000
    histogram = intensity_histogram(write_store(tmp_path / "hot.zarr", data))
    assert histogram is not None
    assert histogram["high"] < 1000
    assert sum(histogram["counts"]) == data.size


def test_uniform_histogram_still_has_a_usable_auto_window(tmp_path):
    data = np.full((4, 8, 8), 42, dtype=np.uint16)
    histogram = intensity_histogram(write_store(tmp_path / "uniform.zarr", data))
    assert histogram is not None
    assert histogram["high"] > histogram["low"]
    assert histogram["autoWindow"] == {"low": 42.0, "high": 43.0}


def test_unreadable_store_has_no_invented_histogram(tmp_path):
    assert intensity_histogram(tmp_path / "missing.zarr") is None


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


def test_one_measurement_answers_all_three_questions(tmp_path):
    """The server asks once and gets a plane window, a volume window and a histogram.

    Reading pixels is the most expensive thing the viewer does when an
    acquisition is first opened, so the three answers come from a single look at
    the data rather than from three separate ones. This checks that the shared
    path agrees with asking each question on its own.
    """
    rng = np.random.default_rng(4)
    data = (500 + rng.integers(0, 4000, size=(8, 64, 64))).astype(np.uint16)
    store = write_store(tmp_path / "measured.zarr", data)

    together = measure(store)

    assert together["window"] == display_window(store)
    assert together["volumeWindow"] == display_window(store, volumetric=True)
    assert together["histogram"] == intensity_histogram(store)


def test_measuring_an_unreadable_store_still_gives_a_usable_window(tmp_path):
    """A store that cannot be read must not stop the viewer from opening.

    A broken or half-written acquisition sitting in the folder should cost that
    one row its histogram, not bring down the whole panel — so the fallback is a
    window covering the full range of the data type, which shows *something*.
    """
    broken = tmp_path / "not-really.zarr"
    broken.mkdir()
    (broken / ".zattrs").write_text("{ this is not json", encoding="utf-8")

    together = measure(broken)

    assert together["window"] == (0.0, 65535.0)
    assert together["volumeWindow"] == (0.0, 65535.0)
    assert together["histogram"] is None

"""What the demo volume must actually contain for the viewer to read it.

These assert concrete numbers, not shapes-and-types: the pyramid stops at three
levels (the fourth would fall below the 8-voxel floor), the physical voxel size
doubles per level, and the intensities land on the project's 800-background /
20800-peak convention. If any of those drift, the viewer still "loads" but shows
the wrong physical scale or a washed-out image, which is exactly the class of
failure that is hard to spot by eye.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import zarr
from demo_data import CHANNEL_COLORS, CHANNEL_NAMES, write_demo_zarr

_BACKGROUND = 800
_PEAK = 20800


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("demo") / "demo.zarr"
    write_demo_zarr(path)
    return path


@pytest.fixture(scope="module")
def attrs(store) -> dict:
    return json.loads((store / ".zattrs").read_text(encoding="utf-8"))


def test_write_returns_the_store_path_and_creates_it(tmp_path):
    out = write_demo_zarr(tmp_path / "x.zarr")
    assert out == tmp_path / "x.zarr"
    assert (out / ".zattrs").is_file()


def test_pyramid_stops_at_three_levels(attrs):
    """A fourth level would be 6 z-planes deep, below the 8-voxel floor."""
    assert len(attrs["multiscales"][0]["datasets"]) == 3


def test_axes_are_channel_plus_three_spatial_in_micrometres(attrs):
    axes = attrs["multiscales"][0]["axes"]
    assert [a["name"] for a in axes] == ["c", "z", "y", "x"]
    assert axes[0]["type"] == "channel"
    assert [a["type"] for a in axes[1:]] == ["space"] * 3
    assert {a["unit"] for a in axes[1:]} == {"micrometer"}


def test_voxel_size_doubles_at_each_level(attrs):
    """z is sampled coarser than x/y, and every level halves the resolution."""
    scales = [
        d["coordinateTransformations"][0]["scale"]
        for d in attrs["multiscales"][0]["datasets"]
    ]
    assert scales == [
        [1.0, 2.0, 0.35, 0.35],
        [1.0, 4.0, 0.70, 0.70],
        [1.0, 8.0, 1.40, 1.40],
    ]


def test_level_shapes_and_chunking(store):
    group = zarr.open_group(str(store), mode="r")
    assert group["0"].shape == (3, 48, 320, 320)
    assert group["1"].shape == (3, 24, 160, 160)
    assert group["2"].shape == (3, 12, 80, 80)
    assert group["0"].chunks == (1, 1, 256, 256)
    assert group["0"].dtype == np.uint16


def test_intensities_span_the_microscope_range(store):
    """One background level everywhere, signal scaled to a 16-bit-ish peak."""
    volume = zarr.open_group(str(store), mode="r")["0"][:]
    assert volume.min() == _BACKGROUND
    assert volume.max() == _PEAK
    for channel in range(3):
        assert volume[channel].max() == _PEAK


def test_structure_channel_is_denser_than_either_marker(store):
    """Markers light up subsets (~55%/~45%) of the cells the structure fills."""
    volume = zarr.open_group(str(store), mode="r")["0"][:]
    threshold = _BACKGROUND + 0.5 * (_PEAK - _BACKGROUND)
    bright = [int((volume[c] > threshold).sum()) for c in range(3)]
    assert bright[0] > bright[1]
    assert bright[0] > bright[2]
    assert bright[0] == pytest.approx(100_414, rel=0.02)
    assert bright[1] == pytest.approx(30_336, rel=0.05)
    assert bright[2] == pytest.approx(35_507, rel=0.05)


def test_same_seed_is_reproducible_and_a_different_seed_is_not(tmp_path):
    a = zarr.open_group(str(write_demo_zarr(tmp_path / "a.zarr", seed=7)), mode="r")["0"][:]
    b = zarr.open_group(str(write_demo_zarr(tmp_path / "b.zarr", seed=7)), mode="r")["0"][:]
    c = zarr.open_group(str(write_demo_zarr(tmp_path / "c.zarr", seed=8)), mode="r")["0"][:]
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_display_hints_name_and_colour_every_channel(attrs):
    channels = attrs["omero"]["channels"]
    assert [c["label"] for c in channels] == list(CHANNEL_NAMES)
    assert [c["color"] for c in channels] == list(CHANNEL_COLORS)
    for channel in channels:
        assert channel["window"]["start"] == float(_BACKGROUND)
        assert channel["window"]["end"] == float(_PEAK)


def test_rewriting_replaces_the_previous_store(tmp_path):
    path = tmp_path / "demo.zarr"
    write_demo_zarr(path, seed=7)
    (path / "stale-file.txt").write_text("left over", encoding="utf-8")
    write_demo_zarr(path, seed=7)
    assert not (path / "stale-file.txt").exists()

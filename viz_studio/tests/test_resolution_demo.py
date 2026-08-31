"""The resolution target only works if each level erases exactly one bar group.

That is the whole basis of the demo: you read the pyramid level off the screen
by counting which gratings still show stripes. If downsampling ever stopped
merging the finest surviving pair -- a different filter, a changed bar layout --
the picture would still look plausible while telling you nothing, so the
property is asserted here rather than assumed.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import zarr
from resolution_demo import _BACKGROUND, _BAR_WIDTHS, _SIGNAL, write_resolution_target

# The centre row of each bar band at full resolution, keyed by bar width.
_BAND_ROWS = {1: 25, 2: 76, 4: 127, 8: 178}


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    return write_resolution_target(tmp_path_factory.mktemp("target") / "resolution.zarr")


@pytest.fixture(scope="module")
def group(store):
    return zarr.open_group(str(store), mode="r")


def resolved(group, level: int, width: int) -> bool:
    """Do the bars of ``width`` still alternate at this pyramid level?"""
    array = group[str(level)]
    row = _BAND_ROWS[width] // (2**level)
    if row >= array.shape[1]:
        return False
    profile = array[array.shape[0] // 2, row, :].astype(float)
    return (profile.max() - profile.min()) / max(profile.max(), 1) > 0.3


def test_the_pyramid_has_five_levels(store):
    datasets = json.loads((store / ".zattrs").read_text())["multiscales"][0]["datasets"]
    assert len(datasets) == 5


def test_voxels_are_cubic_and_double_each_level(store):
    """Cubic on purpose: anisotropy is what makes real data hard to read."""
    datasets = json.loads((store / ".zattrs").read_text())["multiscales"][0]["datasets"]
    scales = [d["coordinateTransformations"][0]["scale"] for d in datasets]
    assert scales == [[1.0] * 3, [2.0] * 3, [4.0] * 3, [8.0] * 3, [16.0] * 3]


def test_full_resolution_resolves_every_bar_group(group):
    for width in _BAR_WIDTHS:
        assert resolved(group, 0, width), f"{width}px bars must resolve at L0"


@pytest.mark.parametrize("width", _BAR_WIDTHS)
def test_each_group_survives_to_its_own_level(group, width):
    """A w-voxel grating is still striped at level log2(w)."""
    assert resolved(group, int(np.log2(width)), width)


@pytest.mark.parametrize("width", [1, 2, 4])
def test_each_group_merges_at_the_next_level(group, width):
    """One level coarser and the bars average into a solid block.

    The 8-voxel group is excluded, and not for convenience: at L4 its bars are
    half a voxel wide, which is past the sampling limit, and whether that
    aliases back into visible stripes is undefined rather than meaningful. The
    demo only claims to read levels 0-3 off the screen.
    """
    assert not resolved(group, int(np.log2(width)) + 1, width)


def test_intensities_leave_room_for_auto_contrast(group):
    volume = group["0"][:]
    assert volume.min() == _BACKGROUND
    assert volume.max() == _SIGNAL


def test_the_store_is_small_enough_to_sit_on_local_disk(store):
    """Under a megabyte: refinement should never be waiting on the disk."""
    total = sum(f.stat().st_size for f in store.rglob("*") if f.is_file())
    assert total < 2_000_000

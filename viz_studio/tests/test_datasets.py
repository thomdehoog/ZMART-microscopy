"""One load is one dataset, and a dataset is one acquisition.

Opening a folder used to produce however many groups its filenames implied: the
text before a store's first underscore was read as its acquisition type, so the
panel's shape came from a naming convention rather than from what the operator
asked for. These tests pin the replacement — the load says what the dataset is,
and the stores in it have to belong together.

What "belong together" means is deliberately read from the data rather than from
the names. Two acquisitions of the same specimen differ in what they are: an
overview is written at one voxel size and a target scan at another. That is the
thing that cannot be faked by renaming a folder, and it is what separates them
here. Channels are reported alongside, because they are what an operator
recognises, but a tile that has not been imaged in every channel yet is a normal
state during a run and is not an error.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import zarr
from library import Library


def _store(path, *, scale=(2.0, 0.35, 0.35), axes=("z", "y", "x"), channels=None):
    """A minimal OME-Zarr with the axes, voxel size and channels asked for."""
    path.mkdir(parents=True)
    shape = tuple(4 if name in "tcz" else 32 for name in axes)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    chunks = tuple(1 if name in "tcz" else 32 for name in axes)
    array = group.create_array("0", shape=shape, chunks=chunks, dtype="uint16")
    array[:] = np.full(shape, 2000, dtype=np.uint16)
    described = {
        "multiscales": [
            {
                "version": "0.4",
                "axes": [{"name": name} for name in axes],
                "datasets": [
                    {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": list(scale)}]}
                ],
            }
        ]
    }
    if channels:
        described["omero"] = {"channels": [{"label": name} for name in channels]}
    (path / ".zattrs").write_text(json.dumps(described), encoding="utf-8")
    return path


def test_tiles_of_one_run_become_one_dataset(tmp_path):
    """Many stores, one dataset — which is the whole point of the change."""
    folder = tmp_path / "run_a"
    for tile in range(4):
        _store(folder / f"overview_pos{tile:03d}.ome.zarr")
    library = Library()
    number = library.open(folder)
    assert library.dataset(number).stores == [
        f"overview_pos{tile:03d}.ome.zarr" for tile in range(4)
    ]


def test_the_dataset_is_named_for_what_was_loaded_not_for_the_filenames(tmp_path):
    """The load names the dataset. Renaming the stores must not rename it."""
    folder = tmp_path / "overview"
    _store(folder / "wildly_unrelated_name.ome.zarr")
    _store(folder / "another_one_entirely.ome.zarr")
    library = Library()
    assert library.dataset(library.open(folder)).name == "overview"


def test_a_folder_holding_two_acquisitions_is_refused(tmp_path):
    """The case the operator has to be told about rather than shown a merge of."""
    folder = tmp_path / "run_b"
    _store(folder / "overview_pos001.ome.zarr", scale=(2.0, 1.30, 1.30))
    _store(folder / "targetscan_cell001.ome.zarr", scale=(2.0, 0.35, 0.35))
    library = Library()
    with pytest.raises(ValueError) as refused:
        library.open(folder)
    assert "more than one acquisition" in str(refused.value)


def test_the_refusal_says_what_it_found_so_the_operator_can_pick(tmp_path):
    """A refusal that does not say what to do instead is a dead end.

    The positive control is the second assertion: it is not enough that an error
    is raised, it has to name both acquisitions and the stores in them.
    """
    folder = tmp_path / "run_c"
    _store(folder / "overview_pos001.ome.zarr", scale=(2.0, 1.30, 1.30))
    _store(folder / "targetscan_cell001.ome.zarr", scale=(2.0, 0.35, 0.35))
    _store(folder / "targetscan_cell002.ome.zarr", scale=(2.0, 0.35, 0.35))
    library = Library()
    with pytest.raises(ValueError) as refused:
        library.open(folder)
    message = str(refused.value)
    assert "overview_pos001.ome.zarr" in message
    assert "targetscan_cell001.ome.zarr" in message
    assert "1.3" in message and "0.35" in message


def test_one_acquisition_may_be_opened_out_of_a_mixed_folder(tmp_path):
    """The way out of the refusal above, and it must actually work."""
    folder = tmp_path / "run_d"
    _store(folder / "overview_pos001.ome.zarr", scale=(2.0, 1.30, 1.30))
    _store(folder / "targetscan_cell001.ome.zarr", scale=(2.0, 0.35, 0.35))
    library = Library()
    number = library.open(folder, names=["targetscan_cell001.ome.zarr"])
    assert library.dataset(number).stores == ["targetscan_cell001.ome.zarr"]


def test_tiles_missing_a_channel_are_not_an_error(tmp_path):
    """During a run a tile exists before every channel of it does.

    The real mesoSPIM transfer this viewer is tested against is exactly this
    shape: two tiles imaged in two channels and a third that has only one so far.
    Refusing that would refuse a live run.
    """
    folder = tmp_path / "run_e"
    _store(folder / "scan_Tile0_Ch488.ome.zarr")
    _store(folder / "scan_Tile0_Ch647.ome.zarr")
    _store(folder / "scan_Tile1_Ch488.ome.zarr")
    library = Library()
    assert len(library.dataset(library.open(folder)).stores) == 3


def test_channels_declared_inside_stores_must_agree(tmp_path):
    """Where a store names its own channels, disagreement is a real mismatch.

    This is the case the "same channels" requirement can actually be checked on:
    both stores claim to hold their channels internally, and they claim different
    ones, so they are not the same acquisition however they are named.
    """
    folder = tmp_path / "run_f"
    axes = ("c", "z", "y", "x")
    _store(folder / "a.ome.zarr", axes=axes, channels=["Ch488", "Ch647"])
    _store(folder / "b.ome.zarr", axes=axes, channels=["Ch405", "Ch561"])
    library = Library()
    with pytest.raises(ValueError) as refused:
        library.open(folder)
    assert "channels" in str(refused.value).lower()


def test_a_dataset_knows_its_channels(tmp_path):
    """What the panel needs in order to show sub-layers without deriving them."""
    folder = tmp_path / "run_g"
    _store(folder / "scan_Tile0_Ch488.ome.zarr")
    _store(folder / "scan_Tile0_Ch647.ome.zarr")
    _store(folder / "scan_Tile1_Ch488.ome.zarr")
    library = Library()
    assert library.dataset(library.open(folder)).channels == ["Ch488", "Ch647"]


def test_two_datasets_open_at_once_stay_apart(tmp_path):
    """Two runs side by side must not pool their tiles into one picture."""
    first, second = tmp_path / "monday", tmp_path / "tuesday"
    _store(first / "overview_pos001.ome.zarr")
    _store(second / "overview_pos001.ome.zarr")
    library = Library()
    one, two = library.open(first), library.open(second)
    assert library.dataset(one).name == "monday"
    assert library.dataset(two).name == "tuesday"
    assert one != two


def test_a_dataset_carries_whether_it_is_live(tmp_path):
    """Mode belongs to the dataset, not to the server: one run may still be
    being written while last week's is open beside it."""
    folder = tmp_path / "run_h"
    _store(folder / "overview_pos001.ome.zarr")
    library = Library()
    assert library.dataset(library.open(folder, watch=True)).live is True
    assert library.dataset(library.open(folder, watch=False)).live is False

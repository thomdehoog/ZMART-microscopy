"""The capture-to-position conversion, pinned on synthetic vendor files.

Both shapes the vendor writes are covered — one file per plane, and one file
holding a whole capture — and what is asserted is the contract the viewer and
the analysis stand on: OME-Zarr 0.5, axes t/c/z/y/x, the stage corner in the
translation, and the pixels round-tripping exactly.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

tifffile = pytest.importorskip("tifffile")
zarr = pytest.importorskip("zarr")

from application.parts.storage.zarr_positions import position_store_from_record


def a_record(planes: list[dict]) -> dict:
    return {"position_label": "K00_M000000_G000000_P000007_V00", "planes": planes}


def one_file_per_plane(folder, *, channels=2, size=256) -> dict:
    """A capture the way the media-path exporter writes it: one YX file each."""
    rng = np.random.default_rng(3)
    planes = []
    for c in range(channels):
        path = folder / f"plane_c{c}.ome.tif"
        image = rng.integers(0, 4000, size=(size, size), dtype=np.uint16)
        ome = (
            '<OME><Image><Pixels PhysicalSizeX="2.5e-06" PhysicalSizeXUnit="m" '
            'PhysicalSizeY="2.5e-06" PhysicalSizeYUnit="m" SizeC="1" /></Pixels>'
            "</Image></OME>"
        )
        tifffile.imwrite(path, image, description=ome)
        planes.append({
            "t": 0, "c": c, "z": 0, "path": str(path),
            "x_um": 1000.0, "y_um": 2000.0, "z_um": -410.0,
        })
    return a_record(planes)


def one_file_whole_capture(folder, *, channels=3, size=128) -> dict:
    """A capture the way LAS X autosave writes it: one CYX file, listed per plane."""
    rng = np.random.default_rng(4)
    path = folder / "Overview001.ome.tif"
    stack = rng.integers(0, 255, size=(channels, size, size), dtype=np.uint8)
    tifffile.imwrite(path, stack, metadata={"axes": "CYX"})
    return a_record([
        {"t": 0, "c": c, "z": 0, "path": str(path),
         "x_um": 500.0, "y_um": 600.0, "z_um": 0.0}
        for c in range(channels)
    ])


class TestTheStore:
    def test_a_position_is_ome_zarr_five_with_tczyx(self, tmp_path):
        store = position_store_from_record(one_file_per_plane(tmp_path), tmp_path / "positions")
        assert store.name == "K00_M000000_G000000_P000007_V00.ome.zarr"
        description = json.loads((store / "zarr.json").read_text())
        assert description["zarr_format"] == 3
        ome = description["attributes"]["ome"]
        assert ome["version"] == "0.5"
        axes = [axis["name"] for axis in ome["multiscales"][0]["axes"]]
        assert axes == ["t", "c", "z", "y", "x"]

    def test_the_pixels_round_trip(self, tmp_path):
        record = one_file_per_plane(tmp_path, channels=2, size=256)
        store = position_store_from_record(record, tmp_path / "positions")
        finest = zarr.open_array(str(store / "0"), mode="r")
        assert finest.shape == (1, 2, 1, 256, 256)
        written = np.asarray(finest[0, 1, 0])
        original = tifffile.imread(record["planes"][1]["path"])
        assert np.array_equal(written, original)

    def test_the_corner_is_the_stage_point_less_half_a_frame(self, tmp_path):
        record = one_file_per_plane(tmp_path, size=256)  # 2.5 um/px -> 640 um frame
        store = position_store_from_record(record, tmp_path / "positions")
        description = json.loads((store / "zarr.json").read_text())
        finest = description["attributes"]["ome"]["multiscales"][0]["datasets"][0]
        kinds = {t["type"]: t for t in finest["coordinateTransformations"]}
        # (t, c, z, y, x): the centre was (x 1000, y 2000), the frame is 640 um.
        assert kinds["translation"]["translation"][3] == pytest.approx(2000.0 - 320.0)
        assert kinds["translation"]["translation"][4] == pytest.approx(1000.0 - 320.0)
        assert kinds["scale"]["scale"][3] == pytest.approx(2.5)
        assert kinds["scale"]["scale"][4] == pytest.approx(2.5)

    def test_a_whole_capture_file_lands_channel_by_channel(self, tmp_path):
        record = one_file_whole_capture(tmp_path, channels=3, size=128)
        store = position_store_from_record(record, tmp_path / "positions")
        finest = zarr.open_array(str(store / "0"), mode="r")
        assert finest.shape == (1, 3, 1, 128, 128)
        original = tifffile.imread(record["planes"][0]["path"])
        for c in range(3):
            assert np.array_equal(np.asarray(finest[0, c, 0]), original[c])

    def test_the_smaller_copies_keep_every_second_voxel(self, tmp_path):
        record = one_file_per_plane(tmp_path, channels=1, size=256)
        store = position_store_from_record(record, tmp_path / "positions")
        finest = zarr.open_array(str(store / "0"), mode="r")
        coarser = zarr.open_array(str(store / "1"), mode="r")
        assert np.array_equal(
            np.asarray(coarser[0, 0, 0]), np.asarray(finest[0, 0, 0])[::2, ::2]
        )

    def test_no_planes_is_a_sentence(self, tmp_path):
        with pytest.raises(RuntimeError, match="no planes"):
            position_store_from_record(a_record([]), tmp_path / "positions")

    def test_an_unspoken_axis_is_refused_by_name(self, tmp_path):
        # A plain 3-D stack with no description: tifffile reports its leading
        # axis as an unknown letter, which the record cannot speak for.
        path = tmp_path / "odd.tif"
        tifffile.imwrite(path, np.zeros((2, 8, 8), dtype=np.uint8))
        record = a_record([
            {"t": 0, "c": 0, "z": 0, "path": str(path), "x_um": 0.0, "y_um": 0.0, "z_um": 0.0}
        ])
        with pytest.raises(RuntimeError, match="axis the record says nothing about"):
            position_store_from_record(record, tmp_path / "positions")

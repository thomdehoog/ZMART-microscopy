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
    return {
        "acquisition_type": "overview",
        "position_label": "K00_M000000_G000000_P000007_V00",
        "planes": planes,
    }


def one_file_per_plane(folder, *, channels=2, size=256) -> dict:
    """A capture the way the media-path exporter writes it: one YX file each."""
    folder.mkdir(parents=True, exist_ok=True)
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


def a_z_stack(
    folder,
    heights=(12.0, 10.0, 8.0),
    *,
    requested_z=10.0,
    acquisition_type="focussing",
) -> dict:
    """A source whose array order runs towards decreasing raw stage Z."""
    planes = []
    for z, height in enumerate(heights):
        path = folder / f"stack_z{z}.ome.tif"
        tifffile.imwrite(path, np.full((64, 64), z + 1, dtype=np.uint16))
        planes.append({
            "t": 0, "c": 0, "z": z, "path": str(path),
            "x_um": 1000.0, "y_um": 2000.0, "z_um": height,
        })
    record = a_record(planes)
    record["acquisition_type"] = acquisition_type
    if requested_z is not None:
        record["requested_position_um"] = {"x": 1000.0, "y": 2000.0, "z": requested_z}
    return record


class TestTheStore:
    def test_a_position_is_ome_zarr_five_with_tczyx(self, tmp_path):
        store = position_store_from_record(one_file_per_plane(tmp_path), tmp_path / "positions")
        assert store.name == "overview_K00_M000000_G000000_P000007_V00.ome.zarr"
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

    def test_focus_height_does_not_turn_a_flat_overview_into_a_stack(self, tmp_path):
        # This one-plane field was acquired at z -410 um. That measured height
        # belongs to the run record, not to the overview's picture geometry:
        # every flat field must occupy the same visible z plane.
        store = position_store_from_record(one_file_per_plane(tmp_path), tmp_path / "positions")
        description = json.loads((store / "zarr.json").read_text())
        finest = description["attributes"]["ome"]["multiscales"][0]["datasets"][0]
        kinds = {t["type"]: t for t in finest["coordinateTransformations"]}
        assert kinds["translation"]["translation"][2] == 0.0
        assert kinds["scale"]["scale"][2] == pytest.approx(1.0)

        model = description["attributes"]["zmart_microscopy"]["z_coordinate"]
        assert model["display_anchor"] == {
            "axis": "z",
            "voxel_index": 0,
            "coordinate_um": 0.0,
            "resolved_by": "only-voxel-center",
            "legacy_fallback": False,
        }
        assert model["source_local"] == {
            "plane_order": [0],
            "spacing_um": 1.0,
            "unit": "micrometer",
            "axis_direction": "single-plane",
        }
        assert model["acquisition_provenance"] == {
            "raw_stage_plane_centres_um": [-410.0],
            "requested_stage_focus_z_um": None,
            "unit": "micrometer",
            "registered_specimen_z": False,
        }

    @pytest.mark.parametrize("acquisition_type", ["overview", "focussing", "target"])
    def test_every_flat_acquisition_type_uses_the_shared_display_anchor(
        self, tmp_path, acquisition_type
    ):
        low = one_file_per_plane(tmp_path / "low", channels=1)
        high = one_file_per_plane(tmp_path / "high", channels=1)
        low["acquisition_type"] = acquisition_type
        high["acquisition_type"] = acquisition_type
        high["position_label"] = "K00_M000000_G000000_P000008_V00"
        high["planes"][0]["z_um"] = 137.5
        stores = [
            position_store_from_record(low, tmp_path / "positions"),
            position_store_from_record(high, tmp_path / "positions"),
        ]
        for store in stores:
            description = json.loads((store / "zarr.json").read_text())
            dataset = description["attributes"]["ome"]["multiscales"][0]["datasets"][0]
            transforms = {item["type"]: item for item in dataset["coordinateTransformations"]}
            anchor = description["attributes"]["zmart_microscopy"]["z_coordinate"][
                "display_anchor"
            ]
            display_z = (
                transforms["translation"]["translation"][2]
                + anchor["voxel_index"] * transforms["scale"]["scale"][2]
            )
            assert display_z == pytest.approx(0.0)

    @pytest.mark.parametrize("acquisition_type", ["overview", "focussing", "target"])
    def test_every_stack_acquisition_type_preserves_local_z_geometry(
        self, tmp_path, acquisition_type
    ):
        store = position_store_from_record(
            a_z_stack(tmp_path, acquisition_type=acquisition_type),
            tmp_path / "positions",
        )
        description = json.loads((store / "zarr.json").read_text())
        dataset = description["attributes"]["ome"]["multiscales"][0]["datasets"][0]
        transforms = {item["type"]: item for item in dataset["coordinateTransformations"]}
        model = description["attributes"]["zmart_microscopy"]["z_coordinate"]

        assert transforms["scale"]["scale"][2] == pytest.approx(-2.0)
        assert transforms["translation"]["translation"][2] == pytest.approx(2.0)
        anchor = model["display_anchor"]["voxel_index"]
        assert anchor == 1
        assert transforms["translation"]["translation"][2] + anchor * -2.0 == pytest.approx(0.0)
        assert model["source_local"] == {
            "plane_order": [0, 1, 2],
            "spacing_um": -2.0,
            "unit": "micrometer",
            "axis_direction": "decreasing",
        }

        provenance = model["acquisition_provenance"]
        assert provenance["raw_stage_plane_centres_um"] == [12.0, 10.0, 8.0]
        assert provenance["requested_stage_focus_z_um"] == 10.0
        assert provenance["registered_specimen_z"] is False

    def test_legacy_stack_fallback_is_resolved_and_recorded_once(self, tmp_path):
        store = position_store_from_record(
            a_z_stack(tmp_path, requested_z=None), tmp_path / "positions"
        )
        description = json.loads((store / "zarr.json").read_text())
        anchor = description["attributes"]["zmart_microscopy"]["z_coordinate"][
            "display_anchor"
        ]
        assert anchor["voxel_index"] == 1
        assert anchor["resolved_by"] == "legacy-middle-plane"
        assert anchor["legacy_fallback"] is True

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


class TestAStoreIsPublishedWhole:
    """The viewer watches ``positions/<type>`` and shows a store as soon as
    its description exists. Filling the levels in place therefore showed a
    store whose zoomed-out copies were still empty. The store is built beside
    the watched folder and renamed into it once every level is filled."""

    def test_the_store_lands_under_its_own_name_and_nothing_is_left_beside_it(self, tmp_path):
        record = one_file_per_plane(tmp_path / "capture", channels=1, size=64)
        positions = tmp_path / "positions" / "overview"
        store = position_store_from_record(record, positions)
        assert store == positions / "overview_K00_M000000_G000000_P000007_V00.ome.zarr"
        assert store.is_dir()
        assert sorted(child.name for child in positions.iterdir()) == [store.name]
        assert not (tmp_path / "positions" / ".writing-overview").exists(), (
            "the staging folder is removed once the store has moved"
        )

    def test_every_level_is_filled_before_the_store_appears(self, tmp_path, monkeypatch):
        """Watched the way the viewer watches: the moment the published name
        exists, all of its copies must already hold pixels."""
        from application.parts.storage import zarr_positions

        record = one_file_per_plane(tmp_path / "capture", channels=1, size=256)
        positions = tmp_path / "positions" / "overview"
        published = positions / "overview_K00_M000000_G000000_P000007_V00.ome.zarr"
        seen_before_publication = []
        original = zarr_positions._publish

        def watched(built, into):
            # the last moment before publication: the watched folder is empty,
            # and the built store already holds every level
            seen_before_publication.append(published.exists())
            for level in ("0", "1"):
                assert (built / level).is_dir(), f"level {level} is written before publication"
                assert any(child.name != "zarr.json" for child in (built / level).rglob("*")), (
                    f"level {level} holds chunks before publication"
                )
            return original(built, into)

        monkeypatch.setattr(zarr_positions, "_publish", watched)
        position_store_from_record(record, positions)
        assert seen_before_publication == [False]

    def test_a_rerun_replaces_the_store_under_the_same_name(self, tmp_path):
        record = one_file_per_plane(tmp_path / "capture", channels=1, size=64)
        positions = tmp_path / "positions" / "overview"
        first = position_store_from_record(record, positions)
        record["planes"][0]["x_um"] = 4321.0
        second = position_store_from_record(record, positions)
        assert first == second
        described = json.loads((second / "zarr.json").read_text(encoding="utf-8"))
        translation = described["attributes"]["ome"]["multiscales"][0]["datasets"][0][
            "coordinateTransformations"
        ]
        assert any(
            abs(one.get("translation", [0] * 5)[-1] - (4321.0 - 64 * 2.5 / 2)) < 1e-6
            for one in translation
        ), "the replaced store carries the new capture's corner"
        assert sorted(child.name for child in positions.iterdir()) == [second.name]
        assert not (tmp_path / "positions" / ".writing-overview").exists()



class TestADeniedRename:
    """Windows denies a rename while another process holds the file.

    Seen on the operator's PC with the interface's own bridge writing beside
    the page: the development server's watcher opened each store's files as
    they appeared, and the writer's rename of ``zarr.json`` into place was
    refused -- one position in three lost, filed as ``zarr_error``, and the
    Viewer never saw the run. A scanner on a microscope PC does the same.
    The write is tried again, in a fresh place, before it is given up on.
    """

    def test_a_rename_denied_once_is_tried_again_and_the_store_is_published(self, tmp_path, monkeypatch):
        import os

        real = os.replace
        denied = {"n": 0}

        def denied_once(src, dst, *args, **kwargs):
            if denied["n"] == 0 and str(dst).endswith("zarr.json"):
                denied["n"] += 1
                raise PermissionError(5, "Access is denied", str(src))
            return real(src, dst, *args, **kwargs)

        monkeypatch.setattr(os, "replace", denied_once)
        store = position_store_from_record(one_file_per_plane(tmp_path), tmp_path / "positions")
        assert denied["n"] == 1
        assert (store / "zarr.json").is_file()
        assert zarr.open_group(str(store), mode="r")["0"].shape[-1] == 256
        assert [p.name for p in (tmp_path / "positions").iterdir()] == [store.name]

    def test_a_rename_denied_every_time_is_the_error_it_was(self, tmp_path, monkeypatch):
        import os

        def always_denied(src, dst, *args, **kwargs):
            if str(dst).endswith("zarr.json"):
                raise PermissionError(5, "Access is denied", str(src))
            return os.rename(src, dst)

        monkeypatch.setattr(os, "replace", always_denied)
        with pytest.raises(PermissionError, match="denied"):
            position_store_from_record(one_file_per_plane(tmp_path), tmp_path / "positions")


def a_frame_at(folder, x_um, y_um, *, value, size=64, name):
    """One single-channel frame of one value, centred at (x, y) on the sample."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.ome.tif"
    ome = (
        '<OME><Image><Pixels PhysicalSizeX="1e-06" PhysicalSizeXUnit="m" '
        'PhysicalSizeY="1e-06" PhysicalSizeYUnit="m" SizeC="1" /></Pixels>'
        "</Image></OME>"
    )
    tifffile.imwrite(path, np.full((size, size), value, dtype=np.uint16), description=ome)
    return {
        "acquisition_type": "targets",
        "position_label": name,
        "planes": [{"t": 0, "c": 0, "z": 0, "path": str(path), "x_um": x_um, "y_um": y_um, "z_um": 0.0}],
    }


def test_the_resolved_store_lets_a_later_frame_overwrite_and_a_raised_one_come_back(tmp_path):
    """The targets acquisition is served to the canvas as ONE store per
    channel, sized to the whole planned set, into which every frame is
    written at its place: where two frames overlap the later one wins, so
    the engine has nothing left to add within a channel. Writing a frame
    again puts it on top -- how the chosen target is raised."""
    from application.parts.storage.zarr_positions import place_into_resolved_store

    planned = [(100.0, 100.0), (140.0, 100.0)]
    first = a_frame_at(tmp_path / "raw", 100.0, 100.0, value=1000, name="P0")
    second = a_frame_at(tmp_path / "raw", 140.0, 100.0, value=2000, name="P1")
    into = tmp_path / "positions" / "targets"

    store = place_into_resolved_store(first, into, planned)
    assert store == into / "targets_resolved.ome.zarr"
    level0 = zarr.open(str(store / "0"), mode="r")
    # the whole planned set: from x 68 to 172, y 68 to 132 -> 104 by 64 voxels
    assert level0.shape[-2:] == (64, 104)
    described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    translation = described["attributes"]["ome"]["multiscales"][0]["datasets"][0]["coordinateTransformations"][1]["translation"]
    assert translation[-2:] == [68.0, 68.0]
    assert level0[0, 0, 0, 10, 10] == 1000 and level0[0, 0, 0, 10, 90] == 0

    place_into_resolved_store(second, into, planned)
    level0 = zarr.open(str(store / "0"), mode="r")
    assert level0[0, 0, 0, 10, 50] == 2000, "the overlap holds the later frame"
    assert level0[0, 0, 0, 10, 10] == 1000 and level0[0, 0, 0, 10, 90] == 2000

    place_into_resolved_store(first, into, planned)
    level0 = zarr.open(str(store / "0"), mode="r")
    assert level0[0, 0, 0, 10, 50] == 1000, "raised: the first frame is on top again"
    assert level0[0, 0, 0, 10, 90] == 2000, "and the rest of the second still stands"

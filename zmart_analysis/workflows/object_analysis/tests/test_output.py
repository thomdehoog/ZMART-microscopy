"""analysis_dir: the folder beside the data the images came from."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "steps"))
import detect_objects  # noqa: E402
from detect_objects import analysis_dir, file_sha256, short_name  # noqa: E402

PLANE =("overview_a1b2c3_K00_M000001_G000001_P000000_V00"
         "_T000000_C00_Z00000.ome.tiff")
FRAME = "overview_a1b2c3_K00_M000001_G000001_P000000_V00_T000000"


def test_the_short_name_drops_the_channel_and_plane():
    assert short_name(PLANE) == FRAME
    assert short_name(f"/runs/overview/data/{PLANE}") == FRAME


def test_every_plane_of_a_frame_shares_one_short_name():
    """Analysis of a frame spans its channels and planes, so they file together."""
    other = PLANE.replace("_C00_Z00000", "_C02_Z00017")
    assert short_name(other) == short_name(PLANE) == FRAME


def test_timepoints_are_kept_apart():
    """T is part of the frame; a later timepoint is a different frame."""
    later = PLANE.replace("_T000000", "_T000004")
    assert short_name(later) != short_name(PLANE)
    assert short_name(later).endswith("_T000004")


def test_a_name_outside_the_convention_keeps_its_stem():
    assert short_name("/loose/tile.ome.tiff") == "tile"


def test_it_sits_beside_the_data_folder():
    found = analysis_dir("/runs/overview/data/tile_r0_c0.ome.tiff")
    assert found == Path("/runs/overview/analysis")


def test_images_nested_under_data_still_resolve():
    found = analysis_dir("/runs/overview/data/region_3/tile_r0_c0.ome.tiff")
    assert found == Path("/runs/overview/analysis")


def test_the_nearest_data_folder_wins():
    """A run inside another acquisition files under its own, not the outer one."""
    found = analysis_dir("/runs/overview/data/nested/data/tile.ome.tiff")
    assert found == Path("/runs/overview/data/nested/analysis")


def test_an_image_outside_an_acquisition_has_no_analysis_folder():
    assert analysis_dir("/somewhere/else/tile.ome.tiff") is None


# --------------------------------------------------------------------------
# The digest of what was analysed: one file, or one position store
# --------------------------------------------------------------------------

STORE = "overview_K00_M000001_G000001_P000000_V00.ome.zarr"


def _a_position_store(folder, *, chunk=b"\x01\x02\x03\x04"):
    """A position store as the writer leaves it: a description and chunks.

    The whole point is that this is a directory, which is what an OME-Zarr
    position is; the digest of one is the digest of everything in it.
    """
    store = folder / STORE
    (store / "0" / "c" / "0" / "0").mkdir(parents=True)
    (store / "1" / "c" / "0" / "0").mkdir(parents=True)
    (store / "zarr.json").write_text('{"zarr_format": 3, "node_type": "group"}')
    (store / "0" / "zarr.json").write_text('{"zarr_format": 3, "node_type": "array"}')
    (store / "0" / "c" / "0" / "0" / "0").write_bytes(chunk)
    (store / "1" / "zarr.json").write_text('{"zarr_format": 3, "node_type": "array"}')
    (store / "1" / "c" / "0" / "0" / "0").write_bytes(chunk[:2])
    return store


def test_a_position_store_has_a_digest_of_everything_in_it(tmp_path):
    """An OME-Zarr position is a directory, and hashing one must not fail.

    Windows refuses to open a directory as a file with "permission denied",
    Linux with "is a directory"; either way the whole detection was lost
    after Cellpose had finished, at the moment its record was written.
    """
    store = _a_position_store(tmp_path / "one")
    digest = file_sha256(store)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert file_sha256(str(store)) == digest, "the same store again is the same digest"


def test_one_changed_chunk_changes_a_store_digest(tmp_path):
    before = file_sha256(_a_position_store(tmp_path / "one"))
    after = file_sha256(_a_position_store(tmp_path / "two", chunk=b"\x01\x02\x03\x05"))
    assert before != after


def test_a_moved_chunk_changes_a_store_digest(tmp_path):
    """Which file holds the bytes is part of what was analysed."""
    store = _a_position_store(tmp_path / "one")
    before = file_sha256(store)
    (store / "0" / "c" / "0" / "0" / "0").rename(store / "0" / "c" / "0" / "0" / "1")
    assert file_sha256(store) != before


def test_a_single_file_digest_is_its_bytes(tmp_path):
    import hashlib

    file = tmp_path / "tile.ome.tiff"
    file.write_bytes(b"not really a tiff")
    assert file_sha256(file) == hashlib.sha256(b"not really a tiff").hexdigest()


def test_a_position_store_files_its_checkpoint_where_the_caller_says(tmp_path):
    """The bridge hands the step a store and the run's analysis folder.

    The record must carry the store's digest and file under the store's own
    name, with nothing about the store read as if it were one file.
    """
    import json

    import numpy as np

    store = _a_position_store(tmp_path / "positions" / "overview")
    masks = np.zeros((8, 8), dtype="int32")
    masks[2:5, 2:5] = 1
    inp = {
        "image_path": str(store),
        "tile_id": ["overview", 0, 0],
        "tile_stage_xy_um": (0.0, 0.0),
        "tile_z_um": 0.0,
        "source_pixel_size_um": (1.0, 1.0),
        "image_to_stage": [[1.0, 0.0], [0.0, 1.0]],
        "output_dir": str(tmp_path / "analysis"),
    }
    artifacts = detect_objects._write_detection_checkpoint(_detection(masks), masks, inp, {})

    written = Path(artifacts["detection_checkpoint_json"])
    assert written.parent == tmp_path / "analysis" / "tiles" / STORE.split(".")[0]
    record = json.loads(written.read_text())
    assert record["image_path"] == str(store)
    assert record["image_sha256"] == file_sha256(store)


# --------------------------------------------------------------------------
# What detect_objects does with it when the caller names no output_dir
# --------------------------------------------------------------------------


def _detection(masks):
    """The fields _write_detection_checkpoint reads, and nothing else."""
    return {
        "masks": masks,
        "n_objects": int(masks.max()),
        "n_raw_objects": int(masks.max()),
        "dropped_labels": [],
        "area_filter": {},
        "border_filter": {"border_margin_px": None},
        "cellpose_params": {},
        "segmentation_params": {},
        "segmentation_params_hash": "0" * 8,
        "segmentation_resize": None,
        "image_size_px": masks.shape[::-1],
    }


def _written_to(tmp_path, image):
    """Run the checkpoint writer for *image*, with no output_dir named."""
    import numpy as np
    import tifffile

    import detect_objects

    image.parent.mkdir(parents=True, exist_ok=True)
    masks = np.zeros((8, 8), dtype="int32")
    masks[2:5, 2:5] = 1
    tifffile.imwrite(image, masks.astype("uint16"))

    inp = {
        "image_path": str(image),
        "tile_id": ("R0", 3, 7),
        "tile_stage_xy_um": (0.0, 0.0),
        "tile_z_um": 0.0,
        "source_pixel_size_um": (1.0, 1.0),
        "image_to_stage": [[1.0, 0.0], [0.0, 1.0]],
    }
    return detect_objects._write_detection_checkpoint(_detection(masks), masks, inp, {})


def test_an_acquisition_image_files_itself_under_analysis(tmp_path):
    image = tmp_path / "overview" / "data" / "tile.ome.tiff"
    artifacts = _written_to(tmp_path, image)

    assert artifacts, "an image inside an acquisition should have written something"
    written = Path(artifacts["detection_checkpoint_json"])
    assert written.is_file()
    assert analysis_dir(image) in written.parents
    assert (tmp_path / "overview" / "analysis").is_dir()


def test_an_image_outside_an_acquisition_writes_nothing(tmp_path):
    image = tmp_path / "loose" / "tile.ome.tiff"
    assert _written_to(tmp_path, image) == {}
    assert not (tmp_path / "loose" / "analysis").exists()

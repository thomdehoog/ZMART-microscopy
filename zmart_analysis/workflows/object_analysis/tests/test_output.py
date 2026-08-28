"""analysis_dir: the folder beside the data the images came from."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from detect_objects import analysis_dir, short_name  # noqa: E402

PLANE = ("overview_a1b2c3_K00_M000001_G000001_P000000_V00"
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
# What detect_objects does with it when the caller names no output_dir
# --------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "steps"))


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
        "tile_zwide_um": 0.0,
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

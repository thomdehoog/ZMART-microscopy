"""The mask picture: honest labels in, a browser-viewable overlay out."""

import numpy as np
import tifffile
from PIL import Image

from application.parts.microscope.mask_view import label_map_of, mask_view_of

LABEL = "K00_M000000_G000000_P000004_V00"


def _a_checkpointed_field(tmp_path):
    data = tmp_path / "overview" / "data"
    data.mkdir(parents=True)
    frame = data / f"overview_abc123_{LABEL}_T000000_C00_Z00000.ome.tiff"
    frame.write_bytes(b"pixels")
    tile = tmp_path / "overview" / "analysis" / "tiles" / f"overview_abc123_{LABEL}_T000000"
    tile.mkdir(parents=True)
    tifffile.imwrite(tile / "masks.tif", np.array([[0, 1], [2, 0]], dtype="int32"))
    return {"planes": [{"path": str(frame)}]}


def test_background_is_transparent_and_each_object_has_its_own_colour(tmp_path):
    record = _a_checkpointed_field(tmp_path)
    view = mask_view_of(record, LABEL)
    assert view is not None and view.is_file()
    px = np.array(Image.open(view))
    assert px[0, 0, 3] == 0, "background must be see-through"
    assert px[0, 1, 3] == 255 and px[1, 0, 3] == 255, "objects must be opaque"
    assert tuple(px[0, 1, :3]) != tuple(px[1, 0, :3]), "two objects, two colours"


def test_a_field_detection_never_visited_answers_none(tmp_path):
    data = tmp_path / "overview" / "data"
    data.mkdir(parents=True)
    frame = data / f"overview_abc123_{LABEL}_T000000_C00_Z00000.ome.tiff"
    frame.write_bytes(b"pixels")
    assert mask_view_of({"planes": [{"path": str(frame)}]}, LABEL) is None


def test_the_view_is_cached_beside_its_mask(tmp_path):
    record = _a_checkpointed_field(tmp_path)
    first = mask_view_of(record, LABEL)
    again = mask_view_of(record, LABEL)
    assert first == again
    assert first.name == "masks_view.png"
    assert first.parent.name.endswith("_T000000")


def test_the_label_map_carries_each_pixels_label_in_its_colour(tmp_path):
    record = _a_checkpointed_field(tmp_path)
    out = label_map_of(record, LABEL)
    assert out is not None and out.name == "masks_labels.png"
    px = np.array(Image.open(out))
    assert px[0, 0, 3] == 0, "background stays see-through"
    assert (px[0, 1, 0], px[0, 1, 1], px[0, 1, 2]) == (1, 0, 0), "label 1 in the low byte"
    assert (px[1, 0, 0], px[1, 0, 1], px[1, 0, 2]) == (2, 0, 0), "label 2 in the low byte"

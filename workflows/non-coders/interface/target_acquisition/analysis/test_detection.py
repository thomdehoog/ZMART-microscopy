"""Detection either side of the analysis: what a field's record becomes, and
what the object table comes back as.

The analysis is handed the capture's OME-Zarr store and nothing it already
holds: where the field lies, its pixel size and its channels are the store's
to say. The pixel size is read from the store here only to put the page's
micrometres into the detector's pixels.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from . import detection


def a_store(folder: Path, *, pixel_um: float = 4.0) -> Path:
    """An OME-Zarr image's description, as a driver writes it: its pixel size in its scale."""
    folder.mkdir(parents=True)
    space = {"type": "space", "unit": "micrometer"}
    (folder / "zarr.json").write_text(json.dumps({
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "axes": [{"name": "t", "type": "time"}, {"name": "c", "type": "channel"},
                     {"name": "z", **space}, {"name": "y", **space}, {"name": "x", **space}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, 1.0, pixel_um, pixel_um]},
                {"type": "translation", "translation": [0.0, 0.0, 8.5, 2000.0, 3000.0]},
            ]}],
        }]}},
    }))
    return folder


def _record(tmp_path: Path, *, channels=(0, 1, 2), pixel_um: float = 4.0) -> dict:
    """A capture as the bridge holds it: its planes, and the store it was saved as."""
    store = a_store(tmp_path / "run" / "overview" / "data" / "f.ome.zarr", pixel_um=pixel_um)
    planes = [
        {"t": 0, "c": c, "z": 0, "path": str(store),
         "x_um": 3000.0, "y_um": 2000.0, "z_um": 8.5}
        for c in channels
    ]
    return {
        "acquisition_type": "overview",
        "position_label": "K00_M000001_G000001_P000004_V00",
        "files": [str(store)], "planes": planes, "zarr": str(store),
    }


def test_the_analysis_is_handed_the_store_and_nothing_it_holds(tmp_path):
    record = _record(tmp_path)

    given = detection.what_was_captured(
        record, field=4, settings={"diameter": 30.0, "cellprob": -1.0}
    )

    assert given["image_path"] == record["zarr"]
    assert given["tile_id"] == ["overview", 4, 0]
    for held in ("tile_stage_xy_um", "tile_z_um", "source_pixel_size_um", "image_to_stage"):
        assert held not in given


def test_the_settings_reach_the_detector_in_its_own_units(tmp_path):
    """The page says a diameter in micrometres; cellpose is told pixels, at the store's pixel size."""
    given = detection.what_was_captured(
        _record(tmp_path), field=0, settings={"diameter": 30.0, "cellprob": -1.0}
    )
    assert given["diameter"] == 7.5
    assert given["cellprob_threshold"] == -1.0
    # How the objects are found rides along in the step's own word, and the
    # fast way's threshold only with it.
    assert given["method"] == "robust"
    assert "threshold" not in given
    fast = detection.what_was_captured(
        _record(tmp_path / "again"), field=0,
        settings={"method": "fast", "diameter": 30.0, "threshold": 250},
    )
    assert fast["method"] == "fast"
    assert fast["threshold"] == 250.0


def test_the_pixel_size_is_the_stores_not_the_microscopes_now(tmp_path):
    """A re-run after the target job was chosen once took the 40x pixel size for the
    10x overview; the store says what the capture was taken at."""
    assert detection.pixel_size_of(_record(tmp_path, pixel_um=0.65)) == 0.65


def test_a_capture_without_a_store_cannot_be_detected_on(tmp_path):
    record = _record(tmp_path)
    del record["zarr"]

    with pytest.raises(RuntimeError, match="store"):
        detection.what_was_captured(record, field=0, settings={})


def test_a_store_that_does_not_say_its_pixel_size_is_refused(tmp_path):
    record = _record(tmp_path)
    description = Path(record["zarr"]) / "zarr.json"
    said = json.loads(description.read_text())
    said["attributes"]["ome"]["multiscales"][0]["datasets"][0]["coordinateTransformations"] = []
    description.write_text(json.dumps(said))

    with pytest.raises(RuntimeError, match="pixel size"):
        detection.what_was_captured(record, field=0, settings={})


def test_a_record_without_planes_cannot_be_detected_on(tmp_path):
    record = _record(tmp_path)
    record["planes"] = []

    with pytest.raises(RuntimeError, match="planes"):
        detection.what_was_captured(record, field=0, settings={})


def test_segmentation_reads_the_first_channel_and_the_rest_ride_along(tmp_path):
    """The store's channels are packed 0..n-1, whatever the instrument numbered them:
    segmentation on channel 0, every other colour measured by index."""
    given = detection.what_was_captured(_record(tmp_path, channels=(1, 2, 3)), field=0, settings={})

    assert given["channels"] == [0]
    assert given["extra_channel_indices"] == [1, 2]


def test_the_chosen_channel_is_segmented_and_the_others_ride_along(tmp_path):
    """The page may choose another colour to find the objects in: that one is
    segmented, and the first becomes a measured colour like the rest."""
    given = detection.what_was_captured(_record(tmp_path), field=0, settings={"channel": 2})

    assert given["channels"] == [2]
    assert given["extra_channel_indices"] == [0, 1]


def test_a_channel_the_capture_does_not_have_is_refused(tmp_path):
    with pytest.raises(ValueError, match="channel 3"):
        detection.what_was_captured(_record(tmp_path), field=0, settings={"channel": 3})


def test_a_single_colour_capture_carries_no_extra_channels(tmp_path):
    given = detection.what_was_captured(_record(tmp_path, channels=(0,)), field=0, settings={})

    assert given["channels"] == [0]
    assert "extra_channel_indices" not in given


def test_the_results_are_filed_beside_the_data(tmp_path):
    given = detection.what_was_captured(_record(tmp_path), field=0, settings={})

    assert Path(given["output_dir"]) == tmp_path / "run" / "overview" / "analysis"


def test_the_results_are_filed_beside_the_captures_data_when_its_store_is_elsewhere(tmp_path):
    """The interface keeps a capture saved as files as a store of its own, in the run's
    ``positions``; the results still go beside the ``data`` its planes were saved in,
    where the page reads the masks from."""
    record = _record(tmp_path)
    record["zarr"] = str(a_store(tmp_path / "run" / "positions" / "overview" / "A1.ome.zarr"))
    for plane in record["planes"]:
        plane["path"] = str(tmp_path / "run" / "overview" / "data" / "A1_C00_Z00000.ome.tiff")

    given = detection.what_was_captured(record, field=0, settings={})

    assert Path(given["output_dir"]) == tmp_path / "run" / "overview" / "analysis"


def test_the_border_margin_reaches_the_detector_in_pixels(tmp_path):
    """The page says micrometres from the field's edge; the detector is told
    pixels -- and zero means the filter is not sent at all."""
    record = _record(tmp_path)
    given = detection.what_was_captured(record, field=0, settings={"border": 20.0})
    assert given["border_margin_px"] == 5.0
    off = detection.what_was_captured(record, field=0, settings={"border": 0})
    assert "border_margin_px" not in off


def test_binning_reaches_the_detector_and_one_means_nothing_sent(tmp_path):
    record = _record(tmp_path)
    given = detection.what_was_captured(record, field=0, settings={"binning": 2})
    assert given["segmentation_binning"] == 2
    full = detection.what_was_captured(record, field=0, settings={"binning": 1})
    assert "segmentation_binning" not in full


def test_the_object_table_comes_back_as_targets_on_the_stage():
    """Each object: where it is on the stage, how large in micrometres, how bright."""
    table = {"objects": {"n_objects": 2, "properties": {
        "object_id": ["overview_r004_c000_obj0001", "overview_r004_c000_obj0002"],
        "label": [1, 2],
        "stage_x_um": [2950.0, 3100.0], "stage_y_um": [1980.0, 2040.0],
        "area": [100, 400], "intensity_mean": [1200.0, 3000.0],
    }}}
    targets = detection.as_targets(table, field=4, pixel_um=4.0)
    assert [t["id"] for t in targets] == [
        "overview_r004_c000_obj0001", "overview_r004_c000_obj0002",
    ]
    assert targets[0] == {
        "id": "overview_r004_c000_obj0001", "field": 4,
        "x": 2950.0, "y": 1980.0,
        "area": 1600.0, "intensity": 1200.0, "r": math.sqrt(1600.0 / math.pi),
        "label": 1,
        # the whole numeric row rides along, raw and unit-less, for the axes
        "features": {
            "label": 1.0, "stage_x_um": 2950.0, "stage_y_um": 1980.0,
            "area": 100.0, "intensity_mean": 1200.0,
        },
    }
    assert targets[1]["area"] == 6400.0


def test_an_empty_table_is_no_targets_not_an_error():
    table = {"objects": {"n_objects": 0, "properties": {
        "object_id": [], "label": [],
        "stage_x_um": [], "stage_y_um": [], "area": [], "intensity_mean": [],
    }}}
    assert detection.as_targets(table, field=0, pixel_um=4.0) == []


def test_through_runs_the_object_pipeline_once_per_field(tmp_path):
    class Analysis:
        def __init__(self):
            self.asked = []

        def run(self, pipeline, given):
            self.asked.append((pipeline, given))
            # The shape the engine hands back: the whole pipeline_data, the
            # table under the pipeline's name and the detection step's own
            # record beside it (its masks stripped, its device kept).
            return {
                "segment_cellpose": {"detector_params": {"device": "cuda", "used_gpu": True}},
                "object_analysis": {"objects": {"n_objects": 1, "properties": {
                    "object_id": ["overview_r000_c000_obj0001"], "label": [7],
                    "stage_x_um": [1.0], "stage_y_um": [2.0], "area": [4], "intensity_mean": [9.0],
                }}},
            }

    analysis = Analysis()
    record = _record(tmp_path)
    find = detection.through(analysis)
    found = find(record, field=0, settings={"diameter": 20.0, "cellprob": 0.0})
    assert analysis.asked[0][0] == "object_analysis_cellpose"
    # The fast way goes through the pipeline that never spawns the vision
    # environment: a cold press paid the torch worker for a watershed.
    find(record, field=0, settings={"method": "fast", "diameter": 20.0})
    assert analysis.asked[1][0] == "object_analysis_watershed"
    assert analysis.asked[1][1]["method"] == "fast"
    find(record, field=0, settings={"method": "robust", "diameter": 20.0})
    assert analysis.asked[2][0] == "object_analysis_cellpose"
    assert analysis.asked[0][1]["diameter"] == 5.0
    targets = found["cells"]
    assert targets[0]["x"] == 1.0 and targets[0]["area"] == 64.0
    # The device rides along with the field: a run that fell back to the
    # CPU took ten minutes a field, and the page could not say so.
    assert found["device"] == "cuda"


def test_a_stack_is_one_channels_planes_in_depth_order():
    """A Leica focus job can carry several channels; interleaving them scored
    a curve of nothing real. The stack is the first channel's planes."""
    from . import focus_score

    record = {"planes": [
        {"t": 0, "c": c, "z": z, "path": f"p_c{c}_z{z}", "z_um": float(z)}
        for z in (2, 0, 1) for c in (0, 1)
    ]}
    given = focus_score.what_was_captured(record)
    assert given["image_paths"] == ["p_c0_z0", "p_c0_z1", "p_c0_z2"]
    assert given["z_um"] == [0.0, 1.0, 2.0]


def test_through_finds_many_fields_at_once_and_says_which_is_which(tmp_path):
    """Fields are independent, so the finder hands them all to the analysis
    and takes the answers as they come, each under its own field."""

    class Analysis:
        def __init__(self):
            self.asked = []

        def run_each(self, pipeline, givens, *, at_once, until=None):
            self.asked.append((pipeline, sorted(givens), at_once))
            for field in reversed(sorted(givens)):
                if field == 1:
                    yield field, RuntimeError("field 1 choked")
                    continue
                yield field, {
                    "segment_watershed": {"detector_params": {"device": "cpu"}},
                    "object_analysis": {"objects": {"n_objects": 1, "properties": {
                        "object_id": [f"overview_r00{field}_c000_obj0001"], "label": [1],
                        "stage_x_um": [float(field)], "stage_y_um": [0.0], "area": [4], "intensity_mean": [1.0],
                    }}},
                }

    analysis = Analysis()
    find = detection.through(analysis)
    records = {field: _record(tmp_path / str(field)) for field in (0, 1, 2)}
    outcomes = dict(find.each(records, settings={"method": "fast"}, at_once=3))
    assert analysis.asked == [("object_analysis_watershed", [0, 1, 2], 3)]
    assert outcomes[0]["cells"][0]["x"] == 0.0 and outcomes[0]["device"] == "cpu"
    assert outcomes[2]["cells"][0]["id"] == "overview_r002_c000_obj0001"
    assert isinstance(outcomes[1], RuntimeError)


def test_how_wide_each_way_of_finding_runs():
    """The watershed is a second of one CPU a field; Cellpose holds a model
    on the card, so it runs one at a time."""
    assert detection.width_of({"method": "robust"}) == 1
    assert detection.width_of({"method": "fast"}) >= 2
    assert detection.width_of({"method": "fast", "at_once": 3}) == 3

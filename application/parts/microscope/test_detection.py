"""Detection either side of the analysis: what a field's record becomes, and
what the object table comes back as.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import math

import pytest

from application.parts.microscope import detection


def _record(**planes_extra):
    planes = [
        {"t": 0, "c": c, "z": 0, "path": f"C:/run/overview/data/f_C0{c}_Z00000.ome.tiff",
         "x_um": 3000.0, "y_um": 2000.0, "z_um": 8.5, **planes_extra}
        for c in (0, 1, 2)
    ]
    return {
        "acquisition_type": "overview", "acquisition_hash": "abc123",
        "position_label": "K00_M000001_G000001_P000004_V00",
        "images": [p["path"] for p in planes], "planes": planes,
    }


def test_the_nuclei_plane_is_what_the_detector_reads():
    given = detection.what_was_captured(
        _record(), field=4, pixel_um=4.0, settings={"diameter": 30.0, "cellprob": -1.0}
    )
    assert given["image_path"].endswith("_C00_Z00000.ome.tiff")
    assert given["tile_id"] == ["overview", 4, 0]
    assert given["tile_stage_xy_um"] == [3000.0, 2000.0]
    assert given["tile_z_um"] == 8.5
    assert given["source_pixel_size_um"] == [4.0, 4.0]
    assert given["image_to_stage"] == [[1.0, 0.0], [0.0, 1.0]]


def test_the_settings_reach_the_detector_in_its_own_units():
    """The page says a diameter in micrometres; cellpose is told pixels."""
    given = detection.what_was_captured(
        _record(), field=0, pixel_um=4.0, settings={"diameter": 30.0, "cellprob": -1.0}
    )
    assert given["diameter"] == 7.5
    assert given["cellprob_threshold"] == -1.0


def test_detection_reads_the_first_channel_the_capture_has():
    """A Leica job's channels can start at 1; requiring the number 0 refused
    it. The lowest channel present is the first channel."""
    record = _record()
    record["planes"] = [p for p in record["planes"] if p["c"] != 0]
    given = detection.what_was_captured(record, field=0, pixel_um=4.0, settings={})
    assert given["image_path"].endswith("_C01_Z00000.ome.tiff")


def test_a_record_without_planes_cannot_be_detected_on():
    with pytest.raises(RuntimeError, match="planes"):
        detection.what_was_captured({"planes": []}, field=0, pixel_um=4.0, settings={})


def test_the_object_table_comes_back_as_targets_on_the_stage():
    """Each object: where it is on the stage, how large in micrometres, how bright."""
    table = {"objects": {"n_objects": 2, "properties": {
        "object_id": ["overview_r004_c000_obj0001", "overview_r004_c000_obj0002"],
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
    }
    assert targets[1]["area"] == 6400.0


def test_an_empty_table_is_no_targets_not_an_error():
    table = {"objects": {"n_objects": 0, "properties": {
        "object_id": [], "stage_x_um": [], "stage_y_um": [], "area": [], "intensity_mean": [],
    }}}
    assert detection.as_targets(table, field=0, pixel_um=4.0) == []


def test_through_runs_the_object_pipeline_once_per_field():
    class Analysis:
        def __init__(self):
            self.asked = []

        def run(self, pipeline, given):
            self.asked.append((pipeline, given))
            return {"object_analysis": {"objects": {"n_objects": 1, "properties": {
                "object_id": ["overview_r000_c000_obj0001"],
                "stage_x_um": [1.0], "stage_y_um": [2.0], "area": [4], "intensity_mean": [9.0],
            }}}}

    analysis = Analysis()
    find = detection.through(analysis, pixel_um=4.0)
    targets = find(_record(), field=0, settings={"diameter": 20.0, "cellprob": 0.0})
    assert analysis.asked[0][0] == "object_analysis"
    assert analysis.asked[0][1]["diameter"] == 5.0
    assert targets[0]["x"] == 1.0 and targets[0]["area"] == 64.0


def test_a_stack_is_one_channels_planes_in_depth_order():
    """A Leica focus job can carry several channels; interleaving them scored
    a curve of nothing real. The stack is the first channel's planes."""
    from application.parts.microscope import focus_score

    record = {"planes": [
        {"t": 0, "c": c, "z": z, "path": f"p_c{c}_z{z}", "z_um": float(z)}
        for z in (2, 0, 1) for c in (0, 1)
    ]}
    given = focus_score.what_was_captured(record)
    assert given["image_paths"] == ["p_c0_z0", "p_c0_z1", "p_c0_z2"]
    assert given["z_um"] == [0.0, 1.0, 2.0]

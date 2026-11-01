"""One focus stack in hand: filed, scored, and reported in the frame the stage drives in."""

from __future__ import annotations

import json

import pytest

from ..storage.output import prepare_acquisition, prepare_experiment
from .focus_run import as_state, measure_one_stack


def a_stack(folder, *, centre=0.0, heights=None, sharp=1.0, label="P0", named=None):
    """A captured stack as a driver answers it: five planes around *centre*,
    each a real file, and the height the sample is sharp at for the stub scorer.
    ``named`` is how the driver began the file names, ``focussing_<label>``
    unless it said otherwise."""
    heights = heights if heights is not None else [centre + (i - 2) * 1.0 for i in range(5)]
    planes = []
    for index, z in enumerate(heights):
        path = folder / f"{named or f'focussing_{label}'}_T000000_C00_Z{index:05d}.ome.tiff"
        path.write_bytes(b"pixels")
        planes.append({"t": 0, "z": index, "c": 0, "z_um": z, "path": str(path)})
    return {
        "acquisition_type": "focussing", "position_label": label,
        "files": [plane["path"] for plane in planes], "planes": planes, "sharp": sharp,
    }


def _score(record):
    """A stand-in for ZMART-analysis: hands back the height the stack was made sharp at."""
    return {"z_um": record["sharp"], "traces": {"brenner": {"samples": []}}}


def test_a_stack_comes_back_as_a_point_of_the_map(tmp_path):
    measured = measure_one_stack(a_stack(tmp_path, sharp=1.5), x=10.0, y=20.0, centre=0.0, score=_score)
    assert (measured["x_um"], measured["y_um"], measured["z_um"]) == (10.0, 20.0, 1.5)
    # A height alone cannot be argued with; the curve is how it shows its work.
    assert measured["traces"] == {"brenner": {"samples": []}}
    assert [plane["z_um"] for plane in measured["planes"]] == [-2.0, -1.0, 0.0, 1.0, 2.0]


def test_the_heights_are_used_as_the_driver_reports_them(tmp_path):
    """Each plane's ``z_um`` is a stage position, by the controller's contract,
    in the frame ``set_xyz`` takes. The interface used to re-centre the planes
    on the height the stage was driven to, which was right only for a stack
    centred there: a stack that starts at the stage and goes up came back
    shifted by half its range, and the overview was imaged that far out of
    focus. Nothing is moved now -- the height, the curves and the planes are
    exactly what the driver and the analysis said."""
    record = a_stack(tmp_path, heights=[5781.8, 5782.8, 5783.8, 5784.8, 5785.8])

    def scored(_record):
        return {"z_um": 5784.2, "traces": {"brenner": {
            "samples": [{"z": 5781.8, "s": 1.0}, {"z": 5785.8, "s": 9.0}], "peak_z_um": 5784.2,
        }}}

    measured = measure_one_stack(record, x=0.0, y=0.0, centre=5781.8, score=scored)
    assert measured["z_um"] == pytest.approx(5784.2)
    curve = measured["traces"]["brenner"]
    assert [s["z"] for s in curve["samples"]] == [pytest.approx(5781.8), pytest.approx(5785.8)]
    assert curve["peak_z_um"] == pytest.approx(5784.2)
    assert [p["z_um"] for p in measured["planes"]] == [5781.8, 5782.8, 5783.8, 5784.8, 5785.8]
    assert "z_shift_um" not in measured


def test_a_stack_nothing_could_be_chosen_from_reports_no_height(tmp_path):
    """A made-up height is worse than a missing one: the surface would believe it."""
    measured = measure_one_stack(
        a_stack(tmp_path), x=0.0, y=0.0, centre=0.0, score=lambda record: {"z_um": None, "traces": {}},
    )
    assert measured["z_um"] is None


def test_a_stack_that_cannot_be_scored_is_lost_not_fatal(tmp_path):
    def broken(_record):
        raise ValueError("one plane cannot be focused")

    measured = measure_one_stack(a_stack(tmp_path), x=0.0, y=0.0, centre=0.0, score=broken)
    assert measured["z_um"] is None and measured["traces"] is None


def test_the_stack_is_filed_under_the_run_and_its_measurement_kept_beside_it(tmp_path):
    run = prepare_experiment(tmp_path / "out", "target-acquisition", hash6="abc123")
    output = prepare_acquisition(run, "focussing")
    staging = tmp_path / "staging"
    staging.mkdir()
    record = a_stack(staging, sharp=0.5)
    kept = []
    measured = measure_one_stack(record, x=1.0, y=2.0, centre=0.0, score=_score,
                                 output=output, keep=kept.append, cost={"capture": 0.25})
    assert kept == [record], "the caller keeps every landed stack, scored or not"
    assert all(str(output) in plane["path"] for plane in record["planes"])
    written = json.loads(next((output / "analysis").glob("*_focus.json")).read_text())
    assert written["z_um"] == 0.5 and written["x_um"] == 1.0
    assert set(measured["cost_s"]) == {"capture", "score"}


def test_a_point_measured_again_keeps_the_first_measurement(tmp_path):
    """The same label taken again: the driver saved the second stack under a
    name of its own in the run's folder, and its measurement stands beside
    the first one's rather than over it."""
    run = prepare_experiment(tmp_path / "out", "target-acquisition", hash6="abc123")
    output = prepare_acquisition(run, "focussing")
    (output / "data").mkdir()
    measure_one_stack(a_stack(output / "data", sharp=0.5), x=1.0, y=2.0, centre=0.0, score=_score, output=output)
    again = a_stack(output / "data", sharp=0.75, named="focussing_P0_001")
    measure_one_stack(again, x=1.0, y=2.0, centre=0.0, score=_score, output=output)
    kept = {path.name: json.loads(path.read_text())["z_um"] for path in (output / "analysis").iterdir()}
    assert kept == {"focussing_P0_T000000_focus.json": 0.5, "focussing_P0_001_T000000_focus.json": 0.75}


def test_recorded_settings_are_wrapped_as_the_driver_reads_them():
    assert as_state({"job": "Focussing"}) == {"changeable": {"job": "Focussing"}}
    whole = {"changeable": {"job": "Focussing"}, "observed": {}}
    assert as_state(whole) is whole

"""The focus chain end to end: drive, acquire a stack, score it, read the height.

This is the step the operator page calls "Create focus map", run against the
mock driver through the controller -- the same path a Leica takes, with no
mock-shaped branch anywhere in it:

    set_xyz    drive to the centre of the range to search
    acquire    the job's z-stack, one 2-D plane per file
    get_state  the stack the job took, so the plane heights are known
    score_focus  sharpness of every plane, and the height it peaks at

What makes it a test rather than a rehearsal is that the mock's sample is a
tilted sheet whose sharp height is a *different number* at every (x, y), and
the run never tells the analysis where it is. If the chain drops the drive, or
scores the wrong planes, or hands back the height it was given, the recovered
peak stops matching ``sharp_height_um`` and the test fails.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from zmart_controller import get_instruments, set_instrument
from application.parts.microscope.focus_score import what_was_captured
from zmart_drivers.mock import mock_driver

# The step is loaded by path rather than imported as a module, the way the
# engine loads it: a step file stands alone, and its own workflow is what puts
# it on a path.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "zmart_analysis/workflows/focus/steps"),
)
from score_focus import run as score_focus  # noqa: E402

#: How close the recovered height must be to the sample's own. The stack steps
#: just over a micrometre, and the parabola refines between planes, so a chain
#: that works lands within two; one that is merely near the middle of the range
#: it swept does not.
TOLERANCE_UM = 2.0

#: Fields the driver puts no dust in, and one it does. Which fields are dusty
#: is a property of where they are, not of when they were acquired, so these
#: can be named -- and a bad point stays bad when the operator presses Rerun.
CLEAN = (-800.0, -200.0)
DUSTY = (-900.0, 0.0)


@pytest.fixture
def scope(tmp_path):
    """A connected mock scope writing into this test's own folder."""
    mock_driver.register_mock()
    instrument = next(i for i in get_instruments() if i["vendor"] == "mock")
    instrument["output_root"] = str(tmp_path)
    session = set_instrument(instrument)
    yield session
    session.disconnect()


def focus_at(session, x_um: float, y_um: float, centre_um: float) -> dict:
    """Drive to (x, y), acquire the stack around *centre_um*, and score it.

    ``focussing`` is what tells the instrument this capture is a stack rather
    than a picture, and the stack is centred on the height driven to -- which
    is the whole reason a caller drives to the middle of the range it wants
    searched rather than to the bottom of it. The heights are worked out from
    what the run did, not read off the record: no driver reports them, and the
    same arithmetic has to serve every driver.
    """
    session.set_xyz(x_um, y_um, centre_um)
    record = session.acquire(acquisition_type="focussing", position_label="K00_P000000")

    scored = score_focus(
        {
            "input": what_was_captured(record),
            "metadata": {"verbose": 0},
        },
        {},
    )["score_focus"]
    return scored


def test_the_height_that_comes_back_is_where_the_sample_is(scope):
    """The chain recovers a height nobody told it, at a place off the origin."""
    truth = mock_driver.sharp_height_um(*CLEAN)

    scored = focus_at(scope, *CLEAN, centre_um=truth + 12.0)

    assert scored["peak_z_um"] == pytest.approx(truth, abs=TOLERANCE_UM)
    assert scored["n_planes"] == 61


def test_the_sample_tilts_so_two_places_focus_at_two_heights(scope):
    """A map is only a map if it can come back uneven."""
    elsewhere = (CLEAN[0] + 50_000.0, CLEAN[1])
    assert mock_driver.debris_at(*elsewhere) is None
    here = mock_driver.sharp_height_um(*CLEAN)
    there = mock_driver.sharp_height_um(*elsewhere)
    assert abs(there - here) > 2 * TOLERANCE_UM  # the sheet really is tilted

    measured_here = focus_at(scope, *CLEAN, centre_um=here)["peak_z_um"]
    measured_there = focus_at(scope, *elsewhere, centre_um=there)["peak_z_um"]

    assert measured_here == pytest.approx(here, abs=TOLERANCE_UM)
    assert measured_there == pytest.approx(there, abs=TOLERANCE_UM)


def test_both_metrics_find_the_same_sample(scope):
    """Gradient-based and entropy-based agree, so the chooser is a real choice.

    The operator page offers both. If they disagreed on a clean stack, the
    choice would be between one right answer and one wrong one rather than
    between two ways of being right.
    """
    truth = mock_driver.sharp_height_um(*CLEAN)

    scored = focus_at(scope, *CLEAN, centre_um=truth)

    for name in ("brenner", "dct"):
        peak = scored["metrics"][name]["peak_index"]
        height = scored["z_um"][0] + peak * (scored["z_um"][1] - scored["z_um"][0])
        assert height == pytest.approx(truth, abs=TOLERANCE_UM), name


def test_a_focus_run_is_not_the_height_it_was_driven_to(scope):
    """Driving to the wrong height still finds the sample, from either side."""
    truth = mock_driver.sharp_height_um(*CLEAN)

    for offset in (-20.0, 20.0):
        scored = focus_at(scope, *CLEAN, centre_um=truth + offset)
        assert scored["peak_z_um"] == pytest.approx(truth, abs=TOLERANCE_UM)
        assert scored["peak_z_um"] != pytest.approx(truth + offset, abs=1e-9)


def test_a_field_with_dust_in_it_comes_back_with_two_peaks(scope):
    """The failure the focus step exists to survive, in real pixels.

    A speck is a hard edge in one plane, so it out-scores the tissue over a far
    narrower range -- which is how an autofocus ends up focused on dust. The
    driver puts one in this field, the acquisition carries it, and the curve
    that comes back has two maxima: the tissue's, and a taller one where the
    speck is. Nothing downstream is told which is which.
    """
    speck = mock_driver.debris_at(*DUSTY)
    assert speck is not None
    tissue = mock_driver.sharp_height_um(*DUSTY)

    scored = focus_at(scope, *DUSTY, centre_um=tissue)

    scores = scored["metrics"]["brenner"]["scores"]
    peaks = [
        index
        for index in range(1, len(scores) - 1)
        if scores[index] > scores[index - 1] and scores[index] > scores[index + 1]
    ]
    assert len(peaks) >= 2, scores
    # The taller one is the speck, at its own height and not the tissue's.
    assert scored["peak_z_um"] == pytest.approx(
        tissue + speck["offset_um"], abs=2 * TOLERANCE_UM
    )
    assert abs(scored["peak_z_um"] - tissue) > TOLERANCE_UM


def test_the_same_field_goes_wrong_the_same_way_twice(scope):
    """Rerun is only useful if a bad point stays bad.

    Dust is a property of where the field is, not of when it was acquired. If
    it were rolled per acquisition, the operator could not tell a fix from a
    reroll, and neither could this test.
    """
    tissue = mock_driver.sharp_height_um(*DUSTY)

    first = focus_at(scope, *DUSTY, centre_um=tissue)
    second = focus_at(scope, *DUSTY, centre_um=tissue)

    assert first["peak_z_um"] == pytest.approx(second["peak_z_um"])
    assert first["metrics"]["brenner"]["scores"] == pytest.approx(
        second["metrics"]["brenner"]["scores"]
    )


def test_dust_is_common_enough_to_meet_and_rare_enough_to_avoid(scope):
    """Roughly two fields in five, so a map of a few points usually shows one."""
    fields = [(x * 100.0, y * 100.0) for x in range(-10, 11) for y in range(-10, 11)]
    dusty = [field for field in fields if mock_driver.debris_at(*field) is not None]
    assert 0.3 < len(dusty) / len(fields) < 0.55


def test_a_capture_that_says_no_heights_is_refused_rather_than_guessed(scope):
    """A record with no places in it cannot be turned into a height.

    Every driver reports where each plane was taken -- it is the only thing
    that knows. One that did not would leave the sharp plane nameable only as
    an index, and inventing micrometres for it would put a focus surface
    through heights nobody measured.
    """
    truth = mock_driver.sharp_height_um(*CLEAN)
    scope.set_xyz(*CLEAN, truth)
    record = scope.acquire(acquisition_type="focussing", position_label="K00_P000000")

    silent = {
        **record,
        "planes": [
            {key: plane[key] for key in ("t", "z", "c", "path")}
            for plane in record["planes"]
        ],
    }

    with pytest.raises(RuntimeError, match="what height each plane was taken at"):
        what_was_captured(silent)


def test_every_plane_says_where_on_the_sample_it_was_taken(scope):
    """x, y and z for every slice, because everything is flat.

    The x and y are the place the stage was driven to and are the same for
    every plane of one capture; the heights are spread about it, because a
    stack is taken around where the drive stands.
    """
    scope.set_xyz(*CLEAN, 5_000.0)
    record = scope.acquire(acquisition_type="focussing", position_label="K00_P000000")

    assert {(plane["x_um"], plane["y_um"]) for plane in record["planes"]} == {CLEAN}
    heights = [plane["z_um"] for plane in record["planes"]]
    assert heights == sorted(heights)
    assert sum(heights) / len(heights) == pytest.approx(5_000.0)
    assert heights[-1] - heights[0] == pytest.approx(68.0)

    given = what_was_captured(record)
    assert given["z_um"] == heights
    assert len(given["image_paths"]) == len(heights) == 61


def test_a_stack_taken_far_from_the_tissue_reports_no_height(scope):
    """The whole point of a search centre: begin in the wrong place and it says so.

    A drive begun far from the sample sweeps its range without reaching it.
    The sharpest plane it holds is only the last one before it stopped, and
    reporting that as the focus would put a surface through a height nobody
    measured -- so nothing is reported.
    """
    truth = mock_driver.sharp_height_um(*CLEAN)

    scored = focus_at(scope, *CLEAN, centre_um=truth + 400.0)

    assert scored["found"] is False
    assert scored["peak_z_um"] is None
    # The curve still came back, because a plot of what it swept is how an
    # operator sees that the search began in the wrong place.
    assert len(scored["metrics"]["brenner"]["scores"]) == 61

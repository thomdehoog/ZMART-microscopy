"""measure_focus drives, acquires a stack, and has it scored; feeds the surface fit."""

from __future__ import annotations

import pytest
from application.workflows.target_acquisition.steps.focus_strategy.focus_run import measure_focus
from application.workflows.target_acquisition.steps.focus_strategy.focus_surface import fit_focus_surface


class _StubSession:
    """Minimal controller session: records moves and captures a scripted stack."""

    def __init__(self, focus_by_xy, current_z=0.0):
        self.focus_by_xy = focus_by_xy
        self.current_z = current_z
        self.moves = []
        self.captured = []
        self.applied = []

    def get_xyz(self):
        return {"z": {"value": self.current_z}}

    def set_xyz(self, x, y, z, **_kw):
        self.moves.append((x, y, z))

    def set_state(self, state):
        self.applied.append(state)
        return {"applied": state}

    def acquire(self, *, acquisition_type, position_label, options=None):
        x, y, _z = self.moves[-1]
        self.captured.append((acquisition_type, position_label, options))
        return {
            "acquisition_type": acquisition_type,
            "planes": [
                {"t": 0, "z": index, "c": 0, "z_um": float(index), "path": f"{x}-{y}-{index}"}
                for index in range(5)
            ],
            # the height this stack was taken around, for the stub scorer
            "focus_by_xy": self.focus_by_xy[(x, y)],
        }


def _score(record):
    """A stand-in for ZMART_analysis: hands back what the stack was built from."""
    return {"z_um": record["focus_by_xy"], "traces": {"brenner": {"samples": []}}}


def test_it_captures_a_focussing_stack_at_every_point():
    session = _StubSession({(0.0, 0.0): 1.0, (10.0, 0.0): 1.5}, current_z=0.3)

    measured = measure_focus(
        session, [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}], score=_score
    )

    assert [(m["x_um"], m["y_um"], m["z_um"]) for m in measured] == [
        (0.0, 0.0, 1.0),
        (10.0, 0.0, 1.5),
    ]
    # A capture, not a vendor procedure -- and named as the kind of scan it is,
    # which is what tells the instrument to take a stack at all.
    assert [kind for kind, _label, _options in session.captured] == ["focussing"] * 2
    assert session.moves[0] == (0.0, 0.0, 0.3)  # start z came from get_xyz


def test_the_curve_comes_back_with_the_height():
    """A height alone cannot be argued with; the curve is how it shows its work."""
    session = _StubSession({(0.0, 0.0): 2.0})
    measured = measure_focus(session, [{"x": 0.0, "y": 0.0}], start_z=0.0, score=_score)
    assert measured[0]["traces"] == {"brenner": {"samples": []}}


def test_the_focussing_settings_are_applied_once_before_the_run():
    session = _StubSession({(0.0, 0.0): 2.0, (10.0, 0.0): 2.0})
    settings = {"changeable": {"job": "AF"}}

    measure_focus(
        session,
        [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
        start_z=0.0,
        state=settings,
        score=_score,
    )

    assert session.applied == [settings]  # once, not per point


def test_every_point_is_named_for_where_it_was_taken():
    """The stacks are files; a file named by nothing cannot be placed later."""
    session = _StubSession({(0.0, 0.0): 1.0, (10.0, 0.0): 1.0})
    measure_focus(
        session, [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}], start_z=0.0, score=_score
    )
    assert [label for _kind, label, _options in session.captured] == [
        "K00_M000000_G000000_P000000_V00",
        "K00_M000000_G000000_P000001_V00",
    ]


def test_a_stack_nothing_could_be_chosen_from_reports_no_height():
    """A made-up height is worse than a missing one: the surface would believe it."""
    session = _StubSession({(0.0, 0.0): 1.0})
    measured = measure_focus(
        session,
        [{"x": 0.0, "y": 0.0}],
        start_z=0.0,
        score=lambda record: {"z_um": None, "traces": {}},
    )
    assert measured[0]["z_um"] is None


def test_measure_then_fit_round_trip():
    focus = {(0.0, 0.0): 3.0, (10.0, 0.0): 4.0, (0.0, 10.0): 5.0}
    session = _StubSession(focus)
    measured = measure_focus(
        session, [{"x": x, "y": y} for x, y in focus], start_z=0.0, score=_score
    )
    surface = fit_focus_surface(measured)
    assert surface.z_at(5, 5) == pytest.approx(4.5)


def test_a_point_that_cannot_be_scored_is_lost_and_the_map_marches_on():
    """One bad point once ended the whole run: the scorer raised on point 1
    and points 2..N were never even acquired. A run is a march, not a chain."""
    session = _StubSession({(0.0, 0.0): 1.0, (10.0, 0.0): 1.5}, current_z=0.3)

    def scoring(record):
        if record["focus_by_xy"] == 1.0:
            raise ValueError("one plane cannot be focused")
        return _score(record)

    measured = measure_focus(
        session, [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}], score=scoring
    )
    assert len(measured) == 2, "the second point was still measured"
    assert measured[0]["z_um"] is None, "the unscorable point is lost, not invented"
    assert measured[1]["z_um"] == 1.5


def test_a_short_capture_is_retaken_until_the_stack_arrives():
    """Fresh settings arm gradually on the LAS X simulator: one plane, then
    two, then the stack. The point is retaken, with patience, until the
    stack is really there -- and the full take is what gets scored."""
    session = _StubSession({(0.0, 0.0): 2.0}, current_z=0.3)
    real_acquire = session.acquire
    calls = {"n": 0}

    def arming_acquire(**kw):
        calls["n"] += 1
        record = real_acquire(**kw)
        if calls["n"] < 3:
            record["planes"] = record["planes"][:calls["n"]]
        return record

    session.acquire = arming_acquire
    measured = measure_focus(session, [{"x": 0.0, "y": 0.0}], score=_score)
    assert calls["n"] == 3, "the takes continued until the stack arrived"
    assert measured[0]["z_um"] == 2.0
    assert len(measured[0]["planes"]) == 5, "the full stack rides the measurement"


def test_a_point_whose_drive_fails_is_lost_and_the_map_marches_on():
    """A flaking position read once ended the run two points in. Every drive
    is absolute, so the next point is untouched by this one's failure."""
    session = _StubSession({(0.0, 0.0): 1.0, (10.0, 0.0): 1.5}, current_z=0.3)
    real_set = session.set_xyz
    def flaky_set(x, y, z, **kw):
        if x == 0.0:
            raise RuntimeError("could not read stage XY position")
        return real_set(x, y, z, **kw)
    session.set_xyz = flaky_set

    measured = measure_focus(
        session, [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}], score=_score
    )
    assert len(measured) == 2
    assert measured[0]["z_um"] is None, "the undriveable point is lost"
    assert measured[1]["z_um"] == 1.5, "the next point was still measured"

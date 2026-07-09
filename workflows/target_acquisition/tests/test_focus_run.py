"""measure_focus drives set_xyz + run_procedure(autofocus); feeds the surface fit."""

from __future__ import annotations

import pytest
from workflow._focus_run import measure_focus
from workflow._focus_surface import fit_focus_surface


class _StubSession:
    """Minimal controller session: records moves, returns a scripted frame focus."""

    def __init__(self, focus_by_xy, current_z=0.0):
        self.focus_by_xy = focus_by_xy
        self.current_z = current_z
        self.moves = []
        self.procedures = []

    def get_xyz(self):
        return {"z": {"value": self.current_z}}

    def set_xyz(self, x, y, z, **_kw):
        self.moves.append((x, y, z))

    def run_procedure(self, procedure):
        self.procedures.append(procedure)
        x, y, _z = self.moves[-1]
        return {"ran": "autofocus", "frame_z_um": self.focus_by_xy[(x, y)]}


def test_visits_points_and_collects_frame_z():
    session = _StubSession({(0.0, 0.0): 1.0, (10.0, 0.0): 1.5}, current_z=0.3)
    measured = measure_focus(
        session, [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}], af_job="AF Job"
    )

    assert measured == [
        {"x_um": 0.0, "y_um": 0.0, "z_um": 1.0},
        {"x_um": 10.0, "y_um": 0.0, "z_um": 1.5},
    ]
    # autofocus job passed through; start z came from get_xyz
    assert session.procedures == [{"name": "autofocus", "job": "AF Job"}] * 2
    assert session.moves[0] == (0.0, 0.0, 0.3)


def test_omitting_af_job_sends_no_job_key():
    session = _StubSession({(0.0, 0.0): 2.0})
    measure_focus(session, [{"x": 0.0, "y": 0.0}], start_z=0.0)
    assert session.procedures == [{"name": "autofocus"}]


def test_measure_then_fit_round_trip():
    focus = {(0.0, 0.0): 3.0, (10.0, 0.0): 4.0, (0.0, 10.0): 5.0}
    session = _StubSession(focus)
    measured = measure_focus(session, [{"x": x, "y": y} for x, y in focus], start_z=0.0)
    surface = fit_focus_surface(measured)
    assert surface.z_at(5, 5) == pytest.approx(4.5)

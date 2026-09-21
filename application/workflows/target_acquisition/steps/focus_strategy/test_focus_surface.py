"""fit_focus_surface: model selection + z(x, y) queries (pure math)."""

from __future__ import annotations

import numpy as np
import pytest
from application.workflows.target_acquisition.steps.focus_strategy.focus_surface import fit_focus_surface


def _pts(triples):
    return [{"x_um": x, "y_um": y, "z_um": z} for x, y, z in triples]


def test_single_point_is_constant():
    surface = fit_focus_surface([{"x_um": 3, "y_um": 4, "z_um": 7.5}])
    assert surface.model == "constant"
    assert surface.z_at(999, -999) == pytest.approx(7.5)


def test_flat_points_give_constant_mean():
    surface = fit_focus_surface(_pts([(0, 0, 5.0), (10, 0, 5.02), (0, 10, 4.99)]))
    assert surface.model == "constant"
    assert surface.z_at(100, 100) == pytest.approx(5.0, abs=0.05)


def test_three_points_fit_a_plane_exactly():
    # z = 0.1x + 0.2y + 3
    surface = fit_focus_surface(_pts([(0, 0, 3.0), (10, 0, 4.0), (0, 10, 5.0)]))
    assert surface.model == "plane"
    assert surface.z_at(5, 5) == pytest.approx(4.5)
    assert surface.z_at(20, 0) == pytest.approx(5.0)


def test_plane_z_at_accepts_arrays():
    surface = fit_focus_surface(_pts([(0, 0, 3.0), (10, 0, 4.0), (0, 10, 5.0)]))
    out = surface.z_at(np.array([0.0, 10.0]), np.array([0.0, 0.0]))
    assert out[0] == pytest.approx(3.0)
    assert out[1] == pytest.approx(4.0)


def test_four_plus_curved_points_give_spline():
    surface = fit_focus_surface(
        _pts([(0, 0, 0.0), (10, 0, 1.0), (0, 10, 1.0), (10, 10, 0.0), (5, 5, 2.0)])
    )
    assert surface.model == "spline"
    # centre peak sits above the corner, and queries stay in a sane range
    assert float(surface.z_at(5, 5)) > float(surface.z_at(0, 0))
    assert 0.0 <= float(surface.z_at(5, 5)) <= 3.0


def test_empty_raises():
    with pytest.raises(ValueError):
        fit_focus_surface([])


# The same table as `parts/microscope/pretend-sample/surface.test.js`, "the
# shared fixture table": a tilted carrier at the rig's absolute stage height,
# points millimetres apart. Every layout that spans the plane must give the
# plane back exactly, in height as well as in tilt; the layouts that cannot
# (one point, points on one line) must still give the measured height at the
# points themselves. Change one file and the other is wrong.
RIG = {"z0": 5781.8, "dzdx": 0.0002, "dzdy": -0.0001}
LAYOUTS = {
    "2 points": [(20600, 10500), (56600, 10500)],
    "3 in a triangle": [(20600, 10500), (56600, 10500), (38600, 30500)],
    "3 on one line": [(0, 0), (14000, 0), (28000, 0)],
    "4 corners": [(20600, 10500), (56600, 10500), (20600, 30500), (56600, 30500)],
    "4 on one line": [(0, 3000), (3000, 3000), (6000, 3000), (9000, 3000)],
    "5 spread": [(20600, 10500), (56600, 10500), (20600, 30500), (56600, 30500), (38600, 20500)],
}
SPANNING = ["3 in a triangle", "4 corners", "5 spread"]
PROBES = [(38600, 20500), (0, 0), (70000, 40000)]


def _rig_z(x, y):
    return RIG["z0"] + RIG["dzdx"] * x + RIG["dzdy"] * y


def _rig(coords):
    return [{"x_um": x, "y_um": y, "z_um": _rig_z(x, y)} for x, y in coords]


@pytest.mark.parametrize("name", list(LAYOUTS))
def test_the_shared_fixture_table_fits_every_measured_point(name):
    surface = fit_focus_surface(_rig(LAYOUTS[name]))
    for x, y in LAYOUTS[name]:
        assert float(surface.z_at(x, y)) == pytest.approx(_rig_z(x, y), abs=1e-6), name


@pytest.mark.parametrize("name", SPANNING)
def test_the_shared_fixture_table_recovers_the_plane_everywhere(name):
    surface = fit_focus_surface(_rig(LAYOUTS[name]))
    for x, y in PROBES:
        assert float(surface.z_at(x, y)) == pytest.approx(_rig_z(x, y), abs=1e-4), name


def test_points_on_one_line_tilt_along_it_and_are_flat_across_it():
    surface = fit_focus_surface(_rig(LAYOUTS["3 on one line"]))
    assert surface.model == "plane"
    assert float(surface.z_at(28000, 0) - surface.z_at(0, 0)) == pytest.approx(RIG["dzdx"] * 28000, abs=1e-6)
    assert float(surface.z_at(14000, 9000)) == pytest.approx(float(surface.z_at(14000, 0)), abs=1e-6)

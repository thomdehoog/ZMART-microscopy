"""fit_focus_surface: model selection + z(x, y) queries (pure math)."""

from __future__ import annotations

import numpy as np
import pytest
from workflow._focus_surface import EXTRAPOLATION_MARGIN_UM, fit_focus_surface


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


def test_far_extrapolation_is_clamped_to_the_safe_range():
    # A tilted plane z = 0.1*x. Measured z spans 0..1 (span 1), so the safe
    # range is [0 - (10+1), 1 + (10+1)] = [-11, 12]. A query far outside the
    # measured footprint (x=1000 -> plane says z=100) must be clamped, not
    # allowed to drive the objective to a runaway z.
    surface = fit_focus_surface(_pts([(0, 0, 0.0), (10, 0, 1.0), (0, 10, 0.0)]))
    span = 1.0
    upper = 1.0 + EXTRAPOLATION_MARGIN_UM + span
    assert float(surface.z_at(1000, 0)) == pytest.approx(upper)
    assert float(surface.z_at(-1000, 0)) == pytest.approx(0.0 - EXTRAPOLATION_MARGIN_UM - span)
    # Inside the measured region the clamp never bites.
    assert float(surface.z_at(5, 0)) == pytest.approx(0.5)


def test_spline_extrapolation_cannot_run_away():
    surface = fit_focus_surface(
        _pts([(0, 0, 0.0), (10, 0, 1.0), (0, 10, 1.0), (10, 10, 0.0), (5, 5, 2.0)])
    )
    lo, hi = surface.z_bounds_um
    # A thin-plate spline diverges far from its points; the clamp holds it.
    assert lo <= float(surface.z_at(10_000, 10_000)) <= hi

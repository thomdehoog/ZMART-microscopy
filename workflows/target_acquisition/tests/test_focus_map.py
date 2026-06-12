"""
Offline unit tests for the pipeline focus map.

These tests exercise the mathematical fitting and interpolation paths only.
They do not call LAS X, move hardware, or require scipy/cellpose.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.focus import FocusMap, _fit_focus_model


def _point(x_um, y_um, zwide_um):
    return {"x_um": float(x_um), "y_um": float(y_um), "zwide_um": float(zwide_um)}


class TestFocusModelFit(unittest.TestCase):
    def test_two_same_z_points_force_constant(self):
        measured = [
            _point(17496.2, 13563.3, 2916.3),
            _point(18215.3, 14350.9, 2916.3),
        ]

        fm = _fit_focus_model(measured)

        self.assertEqual(fm.model, "constant")
        np.testing.assert_allclose(fm.coeffs, [0.0, 0.0, 2916.3])
        np.testing.assert_allclose(fm.residuals_um, [0.0, 0.0])
        self.assertAlmostEqual(float(fm.interpolate_zwide(18000.0, 14000.0)), 2916.3)

    def test_two_different_z_points_fit_line_without_perpendicular_tilt(self):
        measured = [
            _point(0.0, 0.0, 10.0),
            _point(10.0, 10.0, 20.0),
        ]

        fm = _fit_focus_model(measured)

        self.assertEqual(fm.model, "line")
        np.testing.assert_allclose(fm.coeffs, [0.5, 0.5, 15.0], atol=1e-12)
        self.assertAlmostEqual(float(fm.interpolate_zwide(0.0, 0.0)), 10.0)
        self.assertAlmostEqual(float(fm.interpolate_zwide(10.0, 10.0)), 20.0)
        self.assertAlmostEqual(float(fm.interpolate_zwide(10.0, 0.0)), 15.0)

    def test_three_non_collinear_points_fit_centered_plane(self):
        measured = [
            _point(0.0, 0.0, 10.0),
            _point(10.0, 0.0, 20.0),
            _point(0.0, 20.0, 50.0),
        ]

        fm = _fit_focus_model(measured)

        self.assertEqual(fm.model, "plane")
        np.testing.assert_allclose(fm.coeffs[:2], [1.0, 2.0], atol=1e-12)
        self.assertAlmostEqual(float(fm.interpolate_zwide(4.0, 7.0)), 28.0)

    def test_four_collinear_points_fall_back_to_line(self):
        measured = [
            _point(0.0, 0.0, 10.0),
            _point(10.0, 10.0, 20.0),
            _point(20.0, 20.0, 30.0),
            _point(30.0, 30.0, 40.0),
        ]

        fm = _fit_focus_model(measured)

        self.assertEqual(fm.model, "line")
        self.assertIsNotNone(fm.coeffs)
        self.assertIsNone(fm._interpolator)
        self.assertAlmostEqual(float(fm.interpolate_zwide(15.0, 15.0)), 25.0)


class _FakeInterpolator:
    def __init__(self):
        self.last_xy = None

    def __call__(self, xy):
        self.last_xy = np.asarray(xy)
        return self.last_xy[:, 0] + 10.0 * self.last_xy[:, 1]


class TestFocusMapSplineInterpolation(unittest.TestCase):
    def test_spline_interpolate_handles_meshgrid_shape_and_scaling(self):
        interp = _FakeInterpolator()
        fm = FocusMap(
            model="spline",
            coeffs=None,
            origin_xy_um=(100.0, 200.0),
            measured=[],
            residuals_um=np.array([]),
            scale_um=10.0,
            _interpolator=interp,
        )
        gx, gy = np.meshgrid(
            np.array([100.0, 110.0, 120.0]),
            np.array([200.0, 210.0]),
        )

        out = fm.interpolate_zwide(gx, gy)

        self.assertEqual(out.shape, gx.shape)
        self.assertEqual(interp.last_xy.shape, (gx.size, 2))
        np.testing.assert_allclose(
            interp.last_xy,
            np.column_stack(
                [
                    ((gx - 100.0) / 10.0).ravel(),
                    ((gy - 200.0) / 10.0).ravel(),
                ]
            ),
        )

    def test_spline_interpolate_scalar_is_float_compatible(self):
        interp = _FakeInterpolator()
        fm = FocusMap(
            model="spline",
            coeffs=None,
            origin_xy_um=(100.0, 200.0),
            measured=[],
            residuals_um=np.array([]),
            scale_um=10.0,
            _interpolator=interp,
        )

        value = fm.interpolate_zwide(110.0, 220.0)

        self.assertEqual(np.shape(value), ())
        self.assertAlmostEqual(float(value), 21.0)


if __name__ == "__main__":
    unittest.main()

"""
Unit Tests for Alignment / Coordinate Translation
===================================================
Offline tests — no hardware required.

Tests the alignment module: loading calibration data, translating
stage coordinates (motor XY), galvo pan, and z-wide positions between
objectives.

Usage::

    python test_alignment_unit.py
    python -m pytest test_alignment_unit.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lasx.alignment import (
    load_alignment, translate_xy, translate_pan, translate_z, translate_xyz,
    _get_offset,
)
from lasx.utils import PAN_SCALE


# ── Test fixture: minimal calibration data ─────────────────────────────

CALIBRATION = {
    "timestamp": "20260324_202243",
    "ref_objective": "10x/0.40 DRY",
    "ref_label": "slot1_10x",
    "ref_slot": 1,
    "ref_zoom": 10,
    "ref_fov_um": 116.47,
    "ref_pixel_um": 0.2275,
    "ref_z_step_um": 1.0,
    "z_range_um": 40,
    "targets": {
        "slot2_20x": {
            "full_name": "20x/0.75 DRY",
            "slot": 2,
            "shift_xy_px": [-14.7, 21.9],
            "shift_z_slices": 0.1,
            "shift_xy_um": [-3.0, 5.0],
            "shift_z_um": 0.5,
            "motor_delta_um": [-11.0, 18.0],
            "target_pixel_um": 0.2275,
        },
        "slot0_40x": {
            "full_name": "40x/1.10 WATER",
            "slot": 0,
            "shift_xy_px": [15.85, 11.25],
            "shift_z_slices": 8.1,
            "shift_xy_um": [4.0, 3.0],
            "shift_z_um": 8.0,
            "motor_delta_um": [-26.0, 39.0],
            "target_pixel_um": 0.2275,
        },
    },
}


def _write_calibration(data=None):
    """Write calibration JSON to a temp file, return path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data or CALIBRATION, f)
    return path


class TestLoadAlignment(unittest.TestCase):

    def setUp(self):
        self.path = _write_calibration()
        self.al = load_alignment(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_ref_slot(self):
        self.assertEqual(self.al["ref_slot"], 1)

    def test_offsets_keys(self):
        self.assertIn(0, self.al["offsets"])
        self.assertIn(2, self.al["offsets"])
        self.assertNotIn(1, self.al["offsets"])  # ref is implicit

    def test_motor_xy(self):
        self.assertEqual(self.al["offsets"][0]["motor_xy_um"], [-26.0, 39.0])
        self.assertEqual(self.al["offsets"][2]["motor_xy_um"], [-11.0, 18.0])

    def test_image_xy(self):
        self.assertEqual(self.al["offsets"][0]["image_xy_um"], [4.0, 3.0])
        self.assertEqual(self.al["offsets"][2]["image_xy_um"], [-3.0, 5.0])

    def test_total_xy(self):
        # total = motor + image
        self.assertEqual(self.al["offsets"][0]["total_xy_um"], [-22.0, 42.0])
        self.assertEqual(self.al["offsets"][2]["total_xy_um"], [-14.0, 23.0])

    def test_image_z(self):
        self.assertEqual(self.al["offsets"][0]["image_z_um"], 8.0)
        self.assertEqual(self.al["offsets"][2]["image_z_um"], 0.5)


class TestGetOffset(unittest.TestCase):

    def setUp(self):
        self.path = _write_calibration()
        self.al = load_alignment(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_ref_returns_zeros(self):
        off = _get_offset(1, self.al)
        self.assertEqual(off["total_xy_um"], [0.0, 0.0])
        self.assertEqual(off["image_xy_um"], [0.0, 0.0])
        self.assertEqual(off["image_z_um"], 0.0)

    def test_target_returns_data(self):
        off = _get_offset(0, self.al)
        self.assertEqual(off["total_xy_um"], [-22.0, 42.0])

    def test_unknown_slot_raises(self):
        with self.assertRaises(KeyError) as ctx:
            _get_offset(5, self.al)
        self.assertIn("slot 5", str(ctx.exception))


class TestTranslateXY(unittest.TestCase):
    """Stage coordinate translation (motor XY, total offset)."""

    def setUp(self):
        self.path = _write_calibration()
        self.al = load_alignment(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_identity(self):
        x, y = translate_xy(100.0, 200.0, 0, 0, self.al)
        self.assertEqual((x, y), (100.0, 200.0))

    def test_ref_to_target(self):
        # 10x (slot 1) -> 40x (slot 0): add image offset only
        x, y = translate_xy(1000.0, 2000.0, 1, 0, self.al)
        self.assertAlmostEqual(x, 1000.0 - 0.0 + 4.0)
        self.assertAlmostEqual(y, 2000.0 - 0.0 + 3.0)

    def test_target_to_ref(self):
        # 40x -> 10x
        x, y = translate_xy(1004.0, 2003.0, 0, 1, self.al)
        self.assertAlmostEqual(x, 1004.0 - 4.0 + 0.0)
        self.assertAlmostEqual(y, 2003.0 - 3.0 + 0.0)

    def test_round_trip(self):
        x0, y0 = 1000.0, 2000.0
        x1, y1 = translate_xy(x0, y0, 1, 0, self.al)
        x2, y2 = translate_xy(x1, y1, 0, 1, self.al)
        self.assertAlmostEqual(x2, x0, places=10)
        self.assertAlmostEqual(y2, y0, places=10)

    def test_cross_translate(self):
        # 20x -> 40x should equal 20x -> 10x -> 40x
        x_20 = 500.0
        y_20 = 800.0
        x_40_direct, y_40_direct = translate_xy(x_20, y_20, 2, 0, self.al)
        x_10, y_10 = translate_xy(x_20, y_20, 2, 1, self.al)
        x_40_chain, y_40_chain = translate_xy(x_10, y_10, 1, 0, self.al)
        self.assertAlmostEqual(x_40_direct, x_40_chain, places=10)
        self.assertAlmostEqual(y_40_direct, y_40_chain, places=10)


class TestTranslatePan(unittest.TestCase):
    """Galvo pan translation (image offset only)."""

    def setUp(self):
        self.path = _write_calibration()
        self.al = load_alignment(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_identity(self):
        px, py = translate_pan(0.1, 0.2, 0, 0, self.al)
        self.assertEqual((px, py), (0.1, 0.2))

    def test_ref_to_target_uses_image_only(self):
        # 10x -> 40x: image offset is (4.0, 3.0) um
        px, py = translate_pan(0.0, 0.0, 1, 0, self.al)
        self.assertAlmostEqual(px, 4.0 / PAN_SCALE)
        self.assertAlmostEqual(py, 3.0 / PAN_SCALE)

    def test_does_not_use_motor_delta(self):
        # The motor delta for 40x is (-26, 39) um.
        # Pan should NOT include that — only image (4, 3) um.
        px, py = translate_pan(0.0, 0.0, 1, 0, self.al)
        self.assertAlmostEqual(px * PAN_SCALE, 4.0, places=5)
        self.assertAlmostEqual(py * PAN_SCALE, 3.0, places=5)

    def test_round_trip(self):
        px0, py0 = 0.001, -0.002
        px1, py1 = translate_pan(px0, py0, 1, 0, self.al)
        px2, py2 = translate_pan(px1, py1, 0, 1, self.al)
        self.assertAlmostEqual(px2, px0, places=12)
        self.assertAlmostEqual(py2, py0, places=12)

    def test_cross_translate(self):
        px_20, py_20 = translate_pan(0.0, 0.0, 1, 2, self.al)
        px_40_chain, py_40_chain = translate_pan(px_20, py_20, 2, 0, self.al)
        px_40_direct, py_40_direct = translate_pan(0.0, 0.0, 1, 0, self.al)
        self.assertAlmostEqual(px_40_chain, px_40_direct, places=12)
        self.assertAlmostEqual(py_40_chain, py_40_direct, places=12)


class TestTranslateZ(unittest.TestCase):
    """Z-wide (motor Z) parfocal translation."""

    def setUp(self):
        self.path = _write_calibration()
        self.al = load_alignment(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_identity(self):
        z = translate_z(50.0, 0, 0, self.al)
        self.assertEqual(z, 50.0)

    def test_ref_to_target(self):
        # 10x -> 40x: image_z = 8.0 um
        z = translate_z(50.0, 1, 0, self.al)
        self.assertAlmostEqual(z, 58.0)

    def test_round_trip(self):
        z0 = 50.0
        z1 = translate_z(z0, 1, 0, self.al)
        z2 = translate_z(z1, 0, 1, self.al)
        self.assertAlmostEqual(z2, z0, places=10)

    def test_cross_translate(self):
        z_20 = translate_z(50.0, 1, 2, self.al)
        z_40_chain = translate_z(z_20, 2, 0, self.al)
        z_40_direct = translate_z(50.0, 1, 0, self.al)
        self.assertAlmostEqual(z_40_chain, z_40_direct, places=10)


class TestTranslateXYZ(unittest.TestCase):
    """Combined translation convenience function."""

    def setUp(self):
        self.path = _write_calibration()
        self.al = load_alignment(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_matches_individual(self):
        x0, y0, z0 = 1000.0, 2000.0, 50.0
        x1, y1, z1 = translate_xyz(x0, y0, z0, 1, 0, self.al)
        x_exp, y_exp = translate_xy(x0, y0, 1, 0, self.al)
        z_exp = translate_z(z0, 1, 0, self.al)
        self.assertAlmostEqual(x1, x_exp)
        self.assertAlmostEqual(y1, y_exp)
        self.assertAlmostEqual(z1, z_exp)


class TestWithRealCalibration(unittest.TestCase):
    """Test against the actual calibration file if available."""

    CALIBRATION_PATH = os.path.join(
        os.path.dirname(__file__), os.pardir,
        "config", "alignment", "20260324_202243", "alignment_results.json")

    def setUp(self):
        if not os.path.exists(self.CALIBRATION_PATH):
            self.skipTest("Real calibration file not available")
        self.al = load_alignment(self.CALIBRATION_PATH)

    def test_ref_slot(self):
        self.assertEqual(self.al["ref_slot"], 1)

    def test_known_motor_delta_40x(self):
        off = self.al["offsets"][0]
        self.assertAlmostEqual(off["motor_xy_um"][0], -25.708, places=1)
        self.assertAlmostEqual(off["motor_xy_um"][1], 38.501, places=1)

    def test_round_trip_all_slots(self):
        for slot in self.al["offsets"]:
            x0, y0, z0 = 5000.0, 3000.0, 100.0
            x1, y1, z1 = translate_xyz(x0, y0, z0, 1, slot, self.al)
            x2, y2, z2 = translate_xyz(x1, y1, z1, slot, 1, self.al)
            self.assertAlmostEqual(x2, x0, places=8,
                                   msg=f"XY round-trip failed for slot {slot}")
            self.assertAlmostEqual(y2, y0, places=8)
            self.assertAlmostEqual(z2, z0, places=8,
                                   msg=f"Z round-trip failed for slot {slot}")

    def test_pan_uses_image_not_total(self):
        off = self.al["offsets"][0]
        px, py = translate_pan(0.0, 0.0, 1, 0, self.al)
        # Pan offset should match image component, not total
        self.assertAlmostEqual(px * PAN_SCALE, off["image_xy_um"][0], places=5)
        self.assertAlmostEqual(py * PAN_SCALE, off["image_xy_um"][1], places=5)


if __name__ == "__main__":
    unittest.main()

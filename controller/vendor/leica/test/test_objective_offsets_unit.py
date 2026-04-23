"""
Offline tests for objective-switch motor-offset measurement.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lasx.objective_offsets as offsets


HW_INFO = {
    "Microscope": {
        "objectives": [
            {
                "slotIndex": 1,
                "name": "HC PL APO 10x/0.40 DRY",
                "magnification": 10,
                "numericalAperture": 0.4,
                "immersion": "DRY",
                "objectiveNumber": 506511,
            },
            {
                "slotIndex": 2,
                "name": "HC PL APO 20x/0.75 DRY",
                "magnification": 20,
                "numericalAperture": 0.75,
                "immersion": "DRY",
                "objectiveNumber": 506512,
            },
            {
                "slotIndex": 3,
                "name": "HC PL APO 40x/0.95 DRY",
                "magnification": 40,
                "numericalAperture": 0.95,
                "immersion": "DRY",
                "objectiveNumber": 506513,
            },
            {
                "slotIndex": 4,
                "name": "EMPTY",
                "objectiveNumber": 0,
            },
        ]
    }
}


class TestSlotValidation(unittest.TestCase):

    def test_objective_by_slot_ignores_empty_slots(self):
        by_slot = offsets.objective_by_slot(HW_INFO)
        self.assertEqual(sorted(by_slot), [1, 2, 3])
        self.assertEqual(by_slot[2]["magnification"], 20)

    def test_validate_slots_rejects_missing_slot(self):
        with self.assertRaisesRegex(ValueError, "not available"):
            offsets.validate_slots(HW_INFO, 1, [4])

    def test_validate_slots_rejects_reference_as_target(self):
        with self.assertRaisesRegex(ValueError, "reference slot"):
            offsets.validate_slots(HW_INFO, 1, [1])

    def test_validate_slots_rejects_duplicates(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            offsets.validate_slots(HW_INFO, 1, [2, 2])

    def test_validate_slots_rejects_none(self):
        with self.assertRaisesRegex(ValueError, "required"):
            offsets.validate_slots(HW_INFO, 1, None)

    def test_validate_slots_rejects_empty(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            offsets.validate_slots(HW_INFO, 1, [])


class TestPixelToStageXyUm(unittest.TestCase):

    def _config_with_sign(self, matrix):
        return {
            "schema_version": offsets.SCHEMA_VERSION,
            "sign_convention": {"image_to_stage_um_per_um": matrix},
        }

    def test_identity_matrix(self):
        cfg = self._config_with_sign([[1, 0], [0, 1]])
        # Pixel at image centre → stage XY unchanged
        x, y = offsets.pixel_to_stage_xy_um(
            256, 256, (100.0, 200.0), 1.0, 512, cfg,
        )
        self.assertEqual((x, y), (100.0, 200.0))

    def test_identity_offset_from_centre(self):
        cfg = self._config_with_sign([[1, 0], [0, 1]])
        # Pixel 10 to the right of centre → stage +10 um in X
        x, y = offsets.pixel_to_stage_xy_um(
            266, 256, (100.0, 200.0), 1.0, 512, cfg,
        )
        self.assertAlmostEqual(x, 110.0)
        self.assertAlmostEqual(y, 200.0)

    def test_minus_x_plus_y_matrix(self):
        # Scope: image +X = stage -X, image +Y = stage +Y
        cfg = self._config_with_sign([[-1, 0], [0, 1]])
        x, y = offsets.pixel_to_stage_xy_um(
            266, 266, (100.0, 200.0), 1.0, 512, cfg,
        )
        self.assertAlmostEqual(x, 90.0)    # -10 um
        self.assertAlmostEqual(y, 210.0)   # +10 um

    def test_axis_swap_matrix(self):
        # Scope with 90° rotation: image +X = stage +Y, image +Y = stage +X
        cfg = self._config_with_sign([[0, 1], [1, 0]])
        x, y = offsets.pixel_to_stage_xy_um(
            266, 256, (100.0, 200.0), 1.0, 512, cfg,
        )
        # Image offset = (+10, 0) um → stage offset = (0, +10) um
        self.assertAlmostEqual(x, 100.0)
        self.assertAlmostEqual(y, 210.0)

    def test_raises_when_sign_convention_missing(self):
        cfg = {"schema_version": offsets.SCHEMA_VERSION,
               "sign_convention": None}
        with self.assertRaisesRegex(ValueError, "sign_convention"):
            offsets.pixel_to_stage_xy_um(
                0, 0, (0.0, 0.0), 1.0, 512, cfg,
            )

    def test_pixel_size_scales_linearly(self):
        cfg = self._config_with_sign([[1, 0], [0, 1]])
        # 10 pixels at 0.5 um/px → 5 um offset
        x, y = offsets.pixel_to_stage_xy_um(
            266, 256, (0.0, 0.0), 0.5, 512, cfg,
        )
        self.assertAlmostEqual(x, 5.0)
        self.assertAlmostEqual(y, 0.0)


class TestCoordinateConversion(unittest.TestCase):

    def _config(self, deltas, reference_slot=1):
        return {
            "schema_version": offsets.SCHEMA_VERSION,
            "reference_slot": reference_slot,
            "offsets": {
                str(slot): {"motor_delta_um": list(d)}
                for slot, d in deltas.items()
            },
        }

    # reference_to_objective_command_xy (common case: source == reference)

    def test_reference_wrapper_adds_motor_delta(self):
        config = self._config({2: (-7.0, 21.0)})
        x, y = offsets.reference_to_objective_command_xy(100.0, 200.0, config, 2)
        self.assertEqual((x, y), (93.0, 221.0))

    def test_reference_wrapper_accepts_string_slot(self):
        config = self._config({2: (-7.0, 21.0)})
        x, y = offsets.reference_to_objective_command_xy(0.0, 0.0, config, "2")
        self.assertEqual((x, y), (-7.0, 21.0))

    def test_reference_wrapper_raises_on_missing_slot(self):
        config = self._config({2: (-7.0, 21.0)})
        with self.assertRaises(ValueError) as cm:
            offsets.reference_to_objective_command_xy(0.0, 0.0, config, 3)
        self.assertIn("slot 3", str(cm.exception))

    # translate_stage_xy_between_objectives (general case, both directions)

    def test_forward_from_reference(self):
        config = self._config({2: (-7.0, 21.0)})
        x, y = offsets.translate_stage_xy_between_objectives(
            100.0, 200.0, config, from_slot=1, to_slot=2
        )
        self.assertEqual((x, y), (93.0, 221.0))

    def test_reverse_to_reference(self):
        config = self._config({2: (-7.0, 21.0)})
        x, y = offsets.translate_stage_xy_between_objectives(
            93.0, 221.0, config, from_slot=2, to_slot=1
        )
        self.assertEqual((x, y), (100.0, 200.0))

    def test_forward_and_reverse_are_inverse(self):
        config = self._config({2: (-7.0, 21.0)})
        x1, y1 = offsets.translate_stage_xy_between_objectives(
            100.0, 200.0, config, from_slot=1, to_slot=2
        )
        x2, y2 = offsets.translate_stage_xy_between_objectives(
            x1, y1, config, from_slot=2, to_slot=1
        )
        self.assertAlmostEqual(x2, 100.0)
        self.assertAlmostEqual(y2, 200.0)

    def test_identity_when_from_equals_to(self):
        config = self._config({2: (-7.0, 21.0)})
        x, y = offsets.translate_stage_xy_between_objectives(
            100.0, 200.0, config, from_slot=2, to_slot=2
        )
        self.assertEqual((x, y), (100.0, 200.0))

    def test_three_slots_non_reference_pair(self):
        # Neither from_slot nor to_slot is the reference slot.
        config = self._config({2: (-7.0, 21.0), 3: (-20.0, 40.0)})
        x, y = offsets.translate_stage_xy_between_objectives(
            100.0, 200.0, config, from_slot=2, to_slot=3
        )
        # cmd = xy + delta(3) - delta(2) = (100, 200) + (-20, 40) - (-7, 21)
        self.assertEqual((x, y), (87.0, 219.0))

    def test_raises_on_unknown_slot(self):
        config = self._config({2: (-7.0, 21.0)})
        with self.assertRaises(ValueError) as cm:
            offsets.translate_stage_xy_between_objectives(
                0.0, 0.0, config, from_slot=1, to_slot=99
            )
        self.assertIn("slot 99", str(cm.exception))


class TestSaveAndLoad(unittest.TestCase):

    def _config(self):
        return {
            "schema_version": offsets.SCHEMA_VERSION,
            "timestamp": "20260423_120000",
            "offsets": {},
        }

    def test_save_writes_both_archive_and_current(self):
        config = self._config()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            paths = offsets.save_objective_offsets(
                config,
                archive_dir=tmp / "archive",
                current_path=tmp / "current.json",
            )
            self.assertTrue(paths["archive"].exists())
            self.assertTrue(paths["current"].exists())
            self.assertEqual(
                paths["archive"].name,
                f"objective_offsets_{config['timestamp']}.json",
            )

    def test_load_round_trip(self):
        config = self._config()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            paths = offsets.save_objective_offsets(
                config,
                archive_dir=tmp / "archive",
                current_path=tmp / "current.json",
            )
            loaded = offsets.load_objective_offsets(paths["current"])
        self.assertEqual(loaded, config)

    def test_load_rejects_wrong_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrong.json"
            path.write_text(json.dumps({"schema_version": 999, "offsets": {}}),
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema version"):
                offsets.load_objective_offsets(path)

    def test_save_is_atomic(self):
        config = self._config()
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "current.json"
            offsets.save_objective_offsets(
                config,
                archive_dir=Path(tmp) / "archive",
                current_path=current,
            )
            # No .tmp leftover from the atomic-write rename
            self.assertFalse((current.parent / (current.name + ".tmp")).exists())


class TestMeasureObjectiveSwitchOffsets(unittest.TestCase):

    def _patch(self, calls, xy_values, idle_ok=True):
        """Monkey-patch the hardware-facing dependencies of the measurement."""
        def fake_switch(client, job_name, hw_info, slot, *, settle_s):
            calls.append(slot)

        originals = {
            "_switch_slot": offsets._switch_slot,
            "get_xy": offsets.get_xy,
            "check_idle": offsets.check_idle,
        }
        offsets._switch_slot = fake_switch
        offsets.get_xy = lambda client: next(xy_values)
        offsets.check_idle = lambda client, timeout: {"success": idle_ok}

        def restore():
            for name, fn in originals.items():
                setattr(offsets, name, fn)
        return restore

    def test_single_target(self):
        calls = []
        xy = iter([
            {"x_um": 100.0, "y_um": 200.0},  # reference
            {"x_um":  93.0, "y_um": 221.0},  # target
        ])
        restore = self._patch(calls, xy)
        try:
            config = offsets.measure_objective_switch_offsets(
                object(), 1, [2],
                job_name="Overview", hw_info=HW_INFO,
                settle_s=1.0, restore_reference=False,
            )
        finally:
            restore()

        self.assertEqual(calls, [1, 2])

        entry = config["offsets"]["2"]
        self.assertEqual(entry["motor_delta_um"], [-7.0, 21.0])
        self.assertEqual(entry["reference_xy_um"], [100.0, 200.0])
        self.assertEqual(entry["target_xy_um"], [93.0, 221.0])
        self.assertEqual(entry["target_slot"], 2)
        self.assertEqual(entry["target_objective"]["magnification"], 20)

        self.assertEqual(config["reference_slot"], 1)
        self.assertEqual(config["reference_objective"]["slot"], 1)
        self.assertNotIn("start_objective", config)
        self.assertNotIn("residual_xy_correction", config)

    def test_multiple_targets(self):
        calls = []
        xy = iter([
            {"x_um": 100.0, "y_um": 200.0},  # reference (reused)
            {"x_um":  93.0, "y_um": 221.0},  # target 2
            {"x_um":  80.0, "y_um": 240.0},  # target 3
        ])
        restore = self._patch(calls, xy)
        try:
            config = offsets.measure_objective_switch_offsets(
                object(), 1, [2, 3],
                job_name="Overview", hw_info=HW_INFO,
                settle_s=1.0, restore_reference=True,
            )
        finally:
            restore()

        # initial ref, target 2, return to ref, target 3, final restore
        self.assertEqual(calls, [1, 2, 1, 3, 1])
        self.assertEqual(config["offsets"]["2"]["motor_delta_um"], [-7.0, 21.0])
        self.assertEqual(config["offsets"]["3"]["motor_delta_um"], [-20.0, 40.0])

    def test_restore_reference_false(self):
        calls = []
        xy = iter([
            {"x_um": 0.0, "y_um": 0.0},
            {"x_um": 1.0, "y_um": 2.0},
        ])
        restore = self._patch(calls, xy)
        try:
            offsets.measure_objective_switch_offsets(
                object(), 1, [2],
                job_name="Overview", hw_info=HW_INFO,
                settle_s=1.0, restore_reference=False,
            )
        finally:
            restore()
        self.assertEqual(calls, [1, 2])

    def test_rejects_settle_below_minimum(self):
        with self.assertRaisesRegex(ValueError, "settle_s"):
            offsets.measure_objective_switch_offsets(
                object(), 1, [2],
                job_name="Overview", hw_info=HW_INFO,
                settle_s=0.0,
            )

    def test_sign_convention_passes_through(self):
        calls = []
        xy = iter([
            {"x_um": 0.0, "y_um": 0.0},
            {"x_um": 1.0, "y_um": 2.0},
        ])
        restore = self._patch(calls, xy)
        sign = {
            "image_to_stage_um_per_um": [[-1, 0], [0, 1]],
            "label": "-X +Y",
            "move_um": 5.0,
            "residual_from_d4": 0.0,
        }
        try:
            config = offsets.measure_objective_switch_offsets(
                object(), 1, [2],
                job_name="Overview", hw_info=HW_INFO,
                settle_s=1.0, restore_reference=False,
                sign_convention=sign,
            )
        finally:
            restore()
        self.assertEqual(config["sign_convention"], sign)
        self.assertEqual(config["schema_version"], 2)

    def test_aborts_when_lasx_not_idle(self):
        calls = []
        restore = self._patch(calls, iter([]), idle_ok=False)
        try:
            with self.assertRaisesRegex(RuntimeError, "not idle"):
                offsets.measure_objective_switch_offsets(
                    object(), 1, [2],
                    job_name="Overview", hw_info=HW_INFO,
                    settle_s=1.0,
                )
        finally:
            restore()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

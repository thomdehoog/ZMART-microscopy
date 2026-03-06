"""
Integration tests: driver.py + MockLasxClient
===============================================
Tests the driver against the mock API (no hardware, no unittest.mock patches).
This validates that the mock API + driver work together end-to-end.
"""

import sys
import time
import json
import unittest

sys.path.insert(0, "/home/claude")
import driver as drv
from mock_lasx_api import MockLasxClient


class TestMockIntegration(unittest.TestCase):
    """Test driver functions against the mock API."""

    def setUp(self):
        self.client = MockLasxClient(latency=0.001)
        drv.set_stage_limits(
            x_min=0, x_max=130000,
            y_min=0, y_max=100000,
            z_galvo_min=-200, z_galvo_max=200,
            z_wide_min=0, z_wide_max=25000,
        )

    # ── Job selection ──

    def test_select_job_success(self):
        r = drv.select_job(self.client, "HiRes")
        self.assertTrue(r["success"])

    def test_select_fake_job(self):
        r = drv.select_job(self.client, "__FakeJob__")
        # select_job polls, so it will timeout
        self.assertFalse(r["success"])

    # ── Zoom ──

    def test_set_zoom_valid(self):
        r = drv.set_zoom(self.client, "HiRes", 5.0)
        self.assertTrue(r["success"])
        self.assertEqual(r["timing"]["attempts"], 1)
        self.assertEqual(r["timing"]["method"], "async")

    def test_set_zoom_with_readback(self):
        r = drv.set_zoom(self.client, "HiRes", 10.0)
        self.assertTrue(r["success"])
        # Verify readback
        ch = drv.make_changeable_copy(
            drv.get_job_settings(self.client, "HiRes"))
        self.assertAlmostEqual(ch["zoom"]["current"], 10.0, delta=0.1)

    def test_set_zoom_out_of_range(self):
        r = drv.set_zoom(self.client, "HiRes", 999)
        self.assertFalse(r["success"])
        self.assertIn("out of range", r["message"])
        self.assertEqual(r["timing"]["attempts"], 1)  # permanent, no retry

    def test_set_zoom_zero(self):
        r = drv.set_zoom(self.client, "HiRes", 0)
        self.assertFalse(r["success"])

    def test_set_zoom_negative(self):
        r = drv.set_zoom(self.client, "HiRes", -5)
        self.assertFalse(r["success"])

    def test_set_zoom_min_boundary(self):
        r = drv.set_zoom(self.client, "HiRes", 0.75)
        self.assertTrue(r["success"])

    def test_set_zoom_max_boundary(self):
        r = drv.set_zoom(self.client, "HiRes", 48.0)
        self.assertTrue(r["success"])

    def test_set_zoom_fake_job(self):
        r = drv.set_zoom(self.client, "__FakeJob__", 5.0)
        self.assertFalse(r["success"])
        self.assertIn("invalid block identifier", r["message"])

    # ── Scan speed ──

    def test_set_speed_valid(self):
        r = drv.set_scan_speed(self.client, "HiRes", 600)
        self.assertTrue(r["success"])

    def test_set_speed_out_of_range(self):
        r = drv.set_scan_speed(self.client, "HiRes", 99999)
        self.assertFalse(r["success"])

    def test_set_speed_zero(self):
        r = drv.set_scan_speed(self.client, "HiRes", 0)
        self.assertFalse(r["success"])

    # ── Scan field rotation ──

    def test_set_rotation_valid(self):
        r = drv.set_scan_field_rotation(self.client, "HiRes", 45.0)
        self.assertTrue(r["success"])

    def test_set_rotation_out_of_range(self):
        r = drv.set_scan_field_rotation(self.client, "HiRes", 999)
        self.assertFalse(r["success"])

    # ── Pinhole ──

    def test_set_pinhole_valid(self):
        r = drv.set_pinhole_airy(self.client, "HiRes", 0, 1.0)
        self.assertTrue(r["success"])

    def test_set_pinhole_clamped(self):
        """Values outside range get clamped — v5.0 confirmation detects mismatch."""
        r = drv.set_pinhole_airy(self.client, "HiRes", 0, 999)
        # v5.0: confirmation compares readback (clamped) vs target (999)
        # → mismatch → confirmed=False → success=False
        self.assertFalse(r["success"])
        self.assertFalse(r["confirmed"])

    # ── Frame accumulation ──

    def test_set_frame_acc_valid(self):
        r = drv.set_frame_accumulation(self.client, "HiRes", 0, 4)
        self.assertTrue(r["success"])

    def test_set_frame_acc_invalid(self):
        r = drv.set_frame_accumulation(self.client, "HiRes", 0, 99999)
        self.assertFalse(r["success"])
        self.assertIn("is invalid", r["message"])

    # ── Frame average ──

    def test_set_frame_avg_valid(self):
        r = drv.set_frame_average(self.client, "HiRes", 0, 2)
        self.assertTrue(r["success"])

    def test_set_frame_avg_invalid(self):
        r = drv.set_frame_average(self.client, "HiRes", 0, 99999)
        self.assertFalse(r["success"])

    # ── Laser intensity ──

    def test_set_laser_intensity_valid(self):
        r = drv.set_laser_intensity(self.client, "HiRes", 0, "30", 0, 0.5)
        self.assertTrue(r["success"])

    def test_set_laser_intensity_out_of_range(self):
        r = drv.set_laser_intensity(self.client, "HiRes", 0, "30", 0, 5.0)
        self.assertFalse(r["success"])

    def test_set_laser_intensity_fake_br(self):
        r = drv.set_laser_intensity(self.client, "HiRes", 0, "__FakeBR__", 0,
                                    0.5)
        self.assertFalse(r["success"])
        self.assertIn("Invalid light source", r["message"])

    # ── Detector gain ──

    def test_set_detector_gain_valid(self):
        r = drv.set_detector_gain(self.client, "HiRes", 0, "40;3", 2.5)
        self.assertTrue(r["success"])

    def test_set_detector_gain_out_of_range(self):
        r = drv.set_detector_gain(self.client, "HiRes", 0, "40;3", 99999)
        self.assertFalse(r["success"])

    def test_set_detector_gain_fake_br(self):
        r = drv.set_detector_gain(self.client, "HiRes", 0, "__FakeBR__", 50)
        self.assertFalse(r["success"])

    # ── Transient errors (scanner busy) ──

    def test_transient_error_retry(self):
        """When scanner is busy, driver retries after idle."""
        self.client.set_scanning(0.1)  # Busy for 100ms
        r = drv.set_zoom(self.client, "HiRes", 5.0, max_retries=3)
        self.assertTrue(r["success"])
        self.assertGreater(r["timing"]["pre_check_s"], 0)

    # ── Always async ──

    def test_always_async(self):
        r = drv.set_zoom(self.client, "HiRes", 5.0)
        self.assertTrue(r["success"])
        self.assertEqual(r["timing"]["method"], "async")

    # ── Z-stack ──

    def test_set_z_stack_step_size(self):
        r = drv.set_z_stack_step_size(self.client, "HiRes", 2.0)
        self.assertTrue(r["success"])

    def test_set_z_stack_size(self):
        r = drv.set_z_stack_size(self.client, "HiRes", 10.0)
        self.assertTrue(r["success"])

    # ── Sequential mode ──

    def test_set_sequential_mode_valid(self):
        r = drv.set_sequential_mode(self.client, "HiRes", "Frame")
        self.assertTrue(r["success"])

    def test_set_sequential_mode_invalid(self):
        r = drv.set_sequential_mode(self.client, "HiRes", "NotAMode")
        self.assertFalse(r["success"])

    def test_set_sequential_mode_empty(self):
        r = drv.set_sequential_mode(self.client, "HiRes", "")
        self.assertFalse(r["success"])

    # ── Image format ──

    def test_set_image_format(self):
        r = drv.set_image_format(self.client, "HiRes", "1024 x 1024")
        self.assertTrue(r["success"])

    # ── Objective ──

    def test_set_objective(self):
        hw = drv.get_hardware_info(self.client)
        r = drv.set_objective(self.client, "HiRes", hw,
                              name="HC PL APO 63x/1.40 OIL CS2")
        self.assertTrue(r["success"])

    def test_set_objective_not_found(self):
        hw = drv.get_hardware_info(self.client)
        r = drv.set_objective(self.client, "HiRes", hw,
                              name="NonExistentLens")
        self.assertFalse(r["success"])
        self.assertIn("Could not find", r["message"])

    # ── Read functions ──

    def test_get_job_settings(self):
        settings = drv.get_job_settings(self.client, "HiRes")
        self.assertIsNotNone(settings)
        ch = drv.make_changeable_copy(settings)
        self.assertIn("zoom", ch)
        self.assertIn("scanSpeed", ch)
        self.assertIn("activeSettings", ch)

    def test_get_hardware_info(self):
        hw = drv.get_hardware_info(self.client)
        self.assertIsNotNone(hw)
        self.assertIn("Microscope", hw)
        self.assertIn("objectives", hw["Microscope"])

    def test_get_jobs(self):
        jobs = drv.get_jobs(self.client)
        self.assertIsNotNone(jobs)
        names = [j["Name"] for j in jobs]
        self.assertIn("HiRes", names)
        self.assertIn("Overview", names)

    # ── Readback round-trip ──

    def test_set_then_readback(self):
        """Full set → readback cycle validates mock state tracking."""
        # Set multiple params
        drv.set_zoom(self.client, "HiRes", 8.0)
        drv.set_scan_speed(self.client, "HiRes", 200)
        drv.set_frame_accumulation(self.client, "HiRes", 0, 4)
        drv.set_pinhole_airy(self.client, "HiRes", 0, 1.5)

        # Readback
        ch = drv.make_changeable_copy(
            drv.get_job_settings(self.client, "HiRes"))

        self.assertAlmostEqual(ch["zoom"]["current"], 8.0, delta=0.1)
        self.assertEqual(ch["scanSpeed"]["value"], 200)
        self.assertEqual(ch["activeSettings"][0]["frameAccumulation"], 4)
        self.assertAlmostEqual(
            ch["activeSettings"][0]["pinholeAiry"]["value"], 1.5, delta=0.1)

    # ── Stage ──

    def test_move_xy(self):
        r = drv.move_xy(self.client, 50000, 50000)
        self.assertTrue(r["success"])

    def test_move_xy_out_of_limits(self):
        r = drv.move_xy(self.client, 999999, 50000)
        self.assertFalse(r["success"])

    # ── Acquire ──

    def test_acquire(self):
        """Acquire triggers scan and waits for completion."""
        r = drv.acquire(self.client, "HiRes", poll_interval=0.01,
                        settle_time=0.05, start_timeout=2.0)
        self.assertTrue(r["success"])
        self.assertGreater(r["elapsed"], 0)

    # ── Rapid-fire ──

    def test_rapid_zoom_changes(self):
        """Rapid parameter changes should all succeed."""
        for zoom in [1, 2, 3, 5, 8, 10, 12, 15, 20, 25]:
            r = drv.set_zoom(self.client, "HiRes", float(zoom))
            self.assertTrue(r["success"], f"Failed at zoom={zoom}: {r}")

    # ── Multi-job workflow ──

    def test_multi_job_protocol(self):
        """Simulated multi-position acquisition protocol."""
        positions = [
            ("Overview", 10000, 20000, 1.0, 800),
            ("HiRes", 10500, 20500, 5.0, 200),
            ("HiRes", 11200, 20800, 8.0, 100),
            ("Overview", 65000, 50000, 1.0, 800),
        ]

        for job, x, y, zoom, speed in positions:
            r = drv.select_job(self.client, job)
            self.assertTrue(r["success"], f"select_job({job}): {r}")

            r = drv.move_xy(self.client, x, y)
            self.assertTrue(r["success"], f"move_xy({x},{y}): {r}")

            r = drv.set_zoom(self.client, job, zoom)
            self.assertTrue(r["success"], f"set_zoom({zoom}): {r}")

            r = drv.set_scan_speed(self.client, job, speed)
            self.assertTrue(r["success"], f"set_speed({speed}): {r}")


class TestMockTimingRealism(unittest.TestCase):
    """Verify timing instrumentation works with mock API."""

    def setUp(self):
        self.client = MockLasxClient(latency=0.001)

    def test_timing_keys_present(self):
        r = drv.set_zoom(self.client, "HiRes", 5.0)
        t = r["timing"]
        for key in ("pre_check_s", "setup_s", "fire_s", "check_s",
                     "confirm_s", "total_s", "attempts", "method"):
            self.assertIn(key, t)

    def test_timing_total_positive(self):
        r = drv.set_zoom(self.client, "HiRes", 5.0)
        self.assertGreater(r["timing"]["total_s"], 0)

    def test_timing_confirm_always_active(self):
        """v5.0: confirm_fn is baked in, so confirm_s > 0 for success."""
        r = drv.set_zoom(self.client, "HiRes", 5.0)
        self.assertTrue(r["success"])
        self.assertGreater(r["timing"]["confirm_s"], 0)

    def test_confirmed_key_present(self):
        """v5.0 results include 'confirmed' key."""
        r = drv.set_zoom(self.client, "HiRes", 5.0)
        self.assertIn("confirmed", r)
        self.assertTrue(r["confirmed"])


if __name__ == "__main__":
    unittest.main()

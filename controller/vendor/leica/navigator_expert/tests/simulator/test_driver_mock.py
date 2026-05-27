"""Simulator-backed driver tests using ``MockLasxClient``.

These tests run the real driver stack against the stateful in-process
LAS X mock. They are not hardware validation: no LAS X process, stage,
laser, or scanner is touched. Their job is to catch broken wiring
between readers, command dispatch, confirmations, and the mock API
contract before an on-scope validation run.
"""

from __future__ import annotations

import pytest

import navigator_expert.driver as drv
from navigator_expert.driver.core.utils import parse_tile_geometry
from mock_lasx_api import MockLasxClient, _SET_DISPATCH


@pytest.fixture
def client():
    """Mock LAS X client with realistic stage limits for driver commands."""
    mock = MockLasxClient(latency=0.0)
    drv.set_stage_limits(
        x_min=0,
        x_max=130000,
        y_min=0,
        y_max=100000,
        z_galvo_min=-200,
        z_galvo_max=200,
        z_wide_min=0,
        z_wide_max=25000,
    )
    return mock


def _assert_confirmed(result):
    assert result["success"], result
    assert result.get("confirmed") is True, result
    return result


class TestMockContract:
    @pytest.mark.parametrize("command_name, handler_name", sorted(_SET_DISPATCH.items()))
    def test_set_dispatch_table_matches_mock_surface(self, command_name, handler_name):
        mock = MockLasxClient(latency=0.0)
        assert hasattr(mock, command_name)
        assert callable(getattr(mock, handler_name))

    def test_clients_do_not_share_state(self):
        first = MockLasxClient(latency=0.0)
        second = MockLasxClient(latency=0.0)

        _assert_confirmed(drv.set_zoom(first, "HiRes", 7.0))

        second_settings = drv.make_changeable_copy(
            drv.get_job_settings(second, "HiRes", timeout=0.2)
        )
        assert second_settings["zoom"]["current"] == pytest.approx(10.0)

    def test_busy_scanner_rejects_setting_without_retry(self, client):
        client.set_scanning(1.0)

        result = drv.set_zoom(client, "HiRes", 5.0, max_retries=0)

        assert result["success"] is False
        assert result["confirmed"] is None
        assert "being scanned" in result["message"]


class TestMockReaders:
    def test_reads_jobs_hardware_settings_and_geometry(self, client):
        assert drv.ping(client) is True

        jobs = drv.get_jobs(client, timeout=0.2)
        assert {job["Name"] for job in jobs} == {"HiRes", "Overview"}
        assert next(job for job in jobs if job["Name"] == "HiRes")["IsSelected"]

        hardware = drv.get_hardware_info(client, timeout=0.2)
        objectives = hardware["Microscope"]["objectives"]
        assert [obj["slotIndex"] for obj in objectives] == [1, 2, 3]

        raw = drv.get_job_settings(client, "HiRes", timeout=0.2)
        changeable = drv.make_changeable_copy(raw)
        geometry = parse_tile_geometry(raw)

        assert changeable["zoom"]["current"] == 10.0
        assert changeable["format"] == "1024 x 1024"
        assert geometry["pixels_x"] == 1024
        assert geometry["tile_w_um"] == pytest.approx(100.0)

    def test_get_xy_reflects_stage_state(self, client):
        position = drv.get_xy(client, timeout=0.2)
        assert position["x_um"] == pytest.approx(50000.0)
        assert position["y_um"] == pytest.approx(30000.0)


class TestMockCommandRoundTrip:
    def test_setting_commands_confirm_against_mock_readback(self, client):
        _assert_confirmed(drv.set_zoom(client, "HiRes", 5.0))
        _assert_confirmed(drv.set_scan_speed(client, "HiRes", 600))
        _assert_confirmed(drv.set_image_format(client, "HiRes", "512 x 512"))
        _assert_confirmed(drv.set_frame_accumulation(client, "HiRes", 0, 4))
        _assert_confirmed(
            drv.set_laser_intensity(client, "HiRes", 0, "30", 0, 0.2)
        )

        changeable = drv.make_changeable_copy(
            drv.get_job_settings(client, "HiRes", timeout=0.2)
        )
        setting = changeable["activeSettings"][0]
        laser = setting["activeLaserLines"][0]

        assert changeable["zoom"]["current"] == pytest.approx(5.0)
        assert changeable["scanSpeed"]["value"] == 600
        assert changeable["format"] == "512 x 512"
        assert setting["frameAccumulation"] == 4
        assert laser["intensity"]["value"] == pytest.approx(0.2)

    def test_invalid_setting_returns_clean_failure(self, client):
        result = drv.set_zoom(client, "HiRes", 999.0)
        assert result["success"] is False
        assert result["confirmed"] is None
        assert "out of range" in result["message"].lower()

    def test_unknown_job_selection_returns_clean_failure(self, client):
        result = drv.select_job(client, "Ghost", poll_timeout=0.05)
        assert result["success"] is False
        assert result["confirmed"] is False

    def test_motion_and_acquire_confirm_against_mock_state(self, client):
        move = _assert_confirmed(drv.move_xy(client, 52000, 31500, unit="um"))
        assert move["position"]["x_um"] == pytest.approx(52000.0)
        assert move["position"]["y_um"] == pytest.approx(31500.0)

        _assert_confirmed(
            drv.move_z(client, "HiRes", 5.0, unit="um", z_mode="galvo")
        )
        changeable = drv.make_changeable_copy(
            drv.get_job_settings(client, "HiRes", timeout=0.2)
        )
        assert changeable["zPosition"]["z-galvo"] == pytest.approx(5.0)

        acquired = _assert_confirmed(
            drv.acquire(client, "HiRes", poll_interval=0.01, start_timeout=1.0)
        )
        assert acquired["timing"]["method"] == "async"

    def test_objective_switch_confirms_against_slot_readback(self, client):
        hardware = drv.get_hardware_info(client, timeout=0.2)

        _assert_confirmed(
            drv.set_objective(client, "HiRes", hardware, slot_index=2)
        )
        changeable = drv.make_changeable_copy(
            drv.get_job_settings(client, "HiRes", timeout=0.2)
        )
        assert changeable["objective"]["slotIndex"] == 2
        assert changeable["objective"]["magnification"] == 40

        _assert_confirmed(
            drv.set_objective(client, "HiRes", hardware, slot_index=3)
        )

    def test_multi_job_protocol_uses_real_driver_stack(self, client):
        steps = [
            ("Overview", 50000, 30000, 1.0, 800),
            ("HiRes", 50500, 30500, 5.0, 600),
            ("HiRes", 51000, 31000, 8.0, 400),
            ("Overview", 50000, 30000, 1.0, 800),
        ]

        for job_name, x_um, y_um, zoom, speed in steps:
            _assert_confirmed(drv.select_job(client, job_name, poll_timeout=0.2))
            _assert_confirmed(drv.move_xy(client, x_um, y_um, unit="um"))
            _assert_confirmed(drv.set_zoom(client, job_name, zoom))
            _assert_confirmed(drv.set_scan_speed(client, job_name, speed))

        jobs = drv.get_jobs(client, timeout=0.2)
        assert next(job for job in jobs if job["Name"] == "Overview")[
            "IsSelected"
        ]

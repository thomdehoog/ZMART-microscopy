"""Valid command contracts exercised end to end through both MCP and TCP."""
from __future__ import annotations

import json

import pytest

import test_remote_control_transport_harsh as harness


# One representative valid payload for every allowlisted command. ``procedure`` is
# deliberately allowlisted-but-unimplemented, so its valid contract is an explicit error.
VALID_CASES = {
    "hello": {},
    "ping": {},
    "get_state": {},
    "get_position": {},
    "get_state_all": {"keys": ["state", "intensity"]},
    "get_config": {},
    "get_limits": {},
    "get_capabilities": {},
    "get_progress": {},
    "self_test": {},
    "move_absolute": {"targets": {"x": 100}},
    "move_relative": {"deltas": {"x": -1}},
    "zero": {"axes": ["x"]},
    "unzero": {"axes": ["x"]},
    "stop": {},
    "stop_activity": {},
    "set_state": {"settings": {"intensity": 25}},
    "set_filter": {"filter": "Empty", "wait": True},
    "set_zoom": {"zoom": "1x", "wait": True, "update_etl": False},
    "set_laser": {"laser": "488 nm", "wait": True, "update_etl": False},
    "set_intensity": {"intensity": 25, "wait": True},
    "set_shutterconfig": {"shutterconfig": "Left"},
    "set_camera": {"camera_exposure_time": 0.01},
    "set_etl": {"etl_l_amplitude": 1.0},
    "set_galvo": {"galvo_l_frequency": 100.0},
    "set_laser_timing": {"laser_l_delay_%": 10.0},
    "reload_etl_config": {"path": "etl.csv", "wait": True},
    "update_etl_from_laser": {"laser": "488 nm", "wait": True},
    "update_etl_from_zoom": {"zoom": "1x", "wait": True},
    "open_shutters": {},
    "close_shutters": {},
    "snap": {"write": False, "laser_blanking": True},
    "set_mode": {"mode": "idle"},
    "start_live": {},
    "start_visual_mode": {},
    "start_lightsheet_alignment_mode": {},
    "load_sample": {},
    "unload_sample": {},
    "center_sample": {},
    "execute_stage_program": {},
    "save_etl_config": {},
    "get_acquisition_list": {},
    "set_acquisition_list": {"acquisitions": [], "selected_row": 0},
    "run_acquisition_list": {},
    "run_selected_acquisition": {"row": 0},
    "preview_acquisition": {"row": 0, "z_update": True},
    "acquire_start": {"acquisition": {
        "folder": "tmp", "filename": "valid.tif", "planes": 1,
        "laser": "488 nm", "intensity": 10, "filter": "Empty",
        "zoom": "1x", "shutterconfig": "Left",
    }},
    "stat_files": {"files": []},
    "acquire_finish": {},
    "get_disk_space": {},
    "check_motion_limits": {},
    "time_lapse_start": {"timepoints": 1, "interval_sec": 0},
    "time_lapse_stop": {},
    "procedure": {"name": "not-implemented"},
}


EXPECTED_CORE_CALL = {
    "move_absolute": "move_absolute",
    "move_relative": "move_relative",
    "zero": "zero_axes",
    "unzero": "unzero_axes",
    "stop": "sig_stop_movement",
    "stop_activity": "stop",
    "set_state": "state_request_handler",
    "set_filter": "set_filter",
    "set_zoom": "set_zoom",
    "set_laser": "set_laser",
    "set_intensity": "set_intensity",
    "set_shutterconfig": "set_shutterconfig",
    "set_camera": "state_request_handler",
    "set_etl": "state_request_handler",
    "set_galvo": "state_request_handler",
    "set_laser_timing": "state_request_handler",
    "reload_etl_config": "sig_state_request_and_wait_until_done",
    "update_etl_from_laser": "sig_state_request_and_wait_until_done",
    "update_etl_from_zoom": "sig_state_request_and_wait_until_done",
    "open_shutters": "open_shutters",
    "close_shutters": "close_shutters",
    "snap": "snap",
    "set_mode": "stop",
    "start_live": "set_state",
    "start_visual_mode": "set_state",
    "start_lightsheet_alignment_mode": "set_state",
    "load_sample": "sig_load_sample",
    "unload_sample": "sig_unload_sample",
    "center_sample": "sig_center_sample",
    "execute_stage_program": "execute_galil_program",
    "save_etl_config": "sig_save_etl_config",
    "run_acquisition_list": "start",
    "run_selected_acquisition": "start",
    "preview_acquisition": "preview_acquisition",
    "acquire_start": "start",
    "get_disk_space": "get_free_disk_space",
    "check_motion_limits": "check_motion_limits",
    "time_lapse_start": "run_time_lapse",
    "time_lapse_stop": "stop_time_lapse",
}


READ_ONLY_WITHOUT_CORE_CALL = {
    "hello", "ping", "get_state", "get_position", "get_state_all", "get_config",
    "get_limits", "get_capabilities", "get_progress", "self_test",
    "get_acquisition_list", "stat_files",
}


def setup_module(_module=None):
    harness.setup_module()


def teardown_module(_module=None):
    harness.teardown_module()


def _invoke(transport, name, arguments):
    if transport == "mcp":
        status, reply = harness._mcp_tool(name, arguments)
        assert status == 200
        result = reply["result"]
        text = result["content"][0]["text"]
        return not result["isError"], json.loads(text)

    reply = harness._tcp_call({name: arguments})
    if reply.startswith(harness.srv.OK_MARKER):
        return True, json.loads(reply[len(harness.srv.OK_MARKER):])
    return False, {"error": reply}


def test_contract_table_covers_every_allowlisted_command_exactly_once():
    assert set(VALID_CASES) == set(harness.vrc.COMMANDS)
    assert len(VALID_CASES) == 54
    classified = set(EXPECTED_CORE_CALL) | READ_ONLY_WITHOUT_CORE_CALL | {
        "set_acquisition_list", "acquire_finish", "procedure",
    }
    assert classified == set(VALID_CASES)


@pytest.mark.parametrize("transport", ["mcp", "tcp"])
@pytest.mark.parametrize("name", sorted(VALID_CASES))
def test_valid_command_contract_over_both_transports(transport, name):
    harness._core.reset()
    ok, result = _invoke(transport, name, VALID_CASES[name])

    if name == "procedure":
        assert not ok
        assert "not implemented" in result["error"]
        assert harness._core.calls() == []
        return

    assert ok, (transport, name, result)
    assert isinstance(result, dict)
    call_names = [call[0] for call in harness._core.calls()]
    if name in EXPECTED_CORE_CALL:
        assert EXPECTED_CORE_CALL[name] in call_names, (transport, name, call_names)
    elif name in READ_ONLY_WITHOUT_CORE_CALL:
        assert call_names == [], (transport, name, call_names)
    elif name == "set_acquisition_list":
        assert harness._core.state["selected_row"] == 0
    elif name == "acquire_finish":
        assert result["state"] == "idle"

    if name == "move_absolute":
        assert harness._core.state["position"]["x_pos"] == 100
    elif name == "move_relative":
        assert harness._core.state["position"]["x_pos"] == 24998
    elif name == "set_intensity":
        assert harness._core.state["intensity"] == 25
    elif name == "open_shutters":
        assert result["shutterstate"] is True
    elif name == "close_shutters":
        assert result["shutterstate"] is False
    elif name == "self_test":
        assert result["ok"] is True

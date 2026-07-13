"""Opt-in live demo sweep of every mesoSPIM Remote Control command.

This test deliberately drives visible demo state.  It is excluded from normal
CI and refuses to run unless the operator explicitly opts in and the remote
configuration reports a DemoStage.  It exercises all 54 allowlisted commands:
40 instrument-facing operations, 13 read/query commands, and the one
deliberately unimplemented procedure command (which must fail safely).
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import urllib.parse

import pytest

from demo_client import RemoteControl, mcp_call
from test_remote_control_transport_valid import EXPECTED_CORE_CALL, VALID_CASES


pytestmark = pytest.mark.live_demo_all


OPERATIONAL_COMMANDS = set(EXPECTED_CORE_CALL) | {
    "set_acquisition_list",
    "set_mode",
    "stop_activity",
}
assert len(OPERATIONAL_COMMANDS) == 40
assert len(VALID_CASES) == 54


def _live_config():
    required = {
        "MESOSPIM_ALLOW_DEVICE_CHANGE": "1",
        "MESOSPIM_OPERATOR_PRESENT": "1",
        "MESOSPIM_CONFIRM_DEMO_MODE": "1",
        "MESOSPIM_RUN_ALL_COMMANDS": "1",
    }
    for name, expected in required.items():
        if os.environ.get(name) != expected:
            pytest.skip(f"set {name}={expected} to permit the all-command demo sweep")

    url = os.environ.get("MESOSPIM_LIVE_MCP_URL", "http://127.0.0.1:42100/mcp")
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.path != "/mcp" or parsed.port is None):
        raise ValueError("all-command demo sweep requires a loopback http:// MCP URL ending in /mcp")
    token = os.environ.get("MESOSPIM_LIVE_MCP_TOKEN")

    hold = float(os.environ.get("MESOSPIM_DEMO_COMMAND_HOLD_SECONDS", "0.25"))
    if not 0 <= hold <= 1:
        raise ValueError("MESOSPIM_DEMO_COMMAND_HOLD_SECONDS must be between 0 and 1")

    demo_root_text = os.environ.get("MESOSPIM_DEMO_ROOT")
    etl_path_text = os.environ.get("MESOSPIM_DEMO_ETL_CONFIG_PATH")
    process_id_text = os.environ.get("MESOSPIM_DEMO_PROCESS_ID")
    if not demo_root_text or not etl_path_text:
        pytest.skip("set MESOSPIM_DEMO_ROOT and MESOSPIM_DEMO_ETL_CONFIG_PATH for safe file restoration")
    if not process_id_text or not process_id_text.isdigit():
        pytest.skip("set MESOSPIM_DEMO_PROCESS_ID to the current -D mesoSPIM process")
    demo_root = Path(demo_root_text).resolve()
    etl_path = Path(etl_path_text).resolve()
    if not etl_path.is_file() or not etl_path.is_relative_to(demo_root):
        raise ValueError("demo ETL config must be an existing file inside MESOSPIM_DEMO_ROOT")
    return parsed.hostname, parsed.port, token, hold, None, demo_root, etl_path, int(process_id_text)


def _raw_tool(host, port, token, request_timeout, name, arguments=None):
    reply = mcp_call(
        host, port, token, "tools/call", name, arguments or {}, timeout=request_timeout)
    result = reply["result"]
    text = result["content"][0]["text"]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"text": text}
    return not result.get("isError", False), payload


def _raw_tcp_tool(client, name, arguments=None):
    try:
        return True, client.call(name, **(arguments or {}))
    except RuntimeError as exc:
        return False, {"error": str(exc)}


def _must(tool, name, arguments=None):
    ok, result = tool(name, arguments or {})
    if not ok:
        raise AssertionError(f"{name} failed: {result}")
    return result


def _wait_until(predicate, label):
    """Poll without guessing how long a microscope operation should take."""
    while True:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)


def _wait_for_operation(tool, result, label):
    """Wait for the accepted operation itself, not an estimated duration or early idle state."""
    if not isinstance(result, dict) or result.get("accepted") is not True:
        return None
    operation = result.get("operation") or {}
    operation_id = operation.get("id")
    if not operation_id or operation.get("status") == "completed":
        return operation
    if operation.get("status") == "failed":
        raise AssertionError(f"{label} failed: {operation}")

    def terminal():
        current = _must(tool, "get_progress")["operation"]
        if current.get("id") != operation_id:
            raise AssertionError(
                f"{label} operation changed from {operation_id} to {current.get('id')}")
        if current.get("status") == "failed":
            raise AssertionError(f"{label} failed: {current}")
        return current if current.get("status") == "completed" else None

    return _wait_until(terminal, f"{label} operation {operation_id}")


def _different(options, current):
    for option in options:
        if option != current:
            return option
    raise AssertionError(f"no alternate option available for {current!r}")


def _bounded_delta(value, low, high, delta):
    candidate = float(value) + delta
    if candidate > high:
        candidate = float(value) - delta
    if not low <= candidate <= high or candidate == value:
        candidate = (low + high) / 2
    return candidate


def _demo_acquisition(folder, filename, state):
    pos = state["position"]
    return {
        "x_pos": pos["x_pos"],
        "y_pos": pos["y_pos"],
        "z_start": pos["z_pos"],
        "z_end": pos["z_pos"],
        "z_step": 1,
        "planes": 1,
        "rot": pos["theta_pos"],
        "f_start": pos["f_pos"],
        "f_end": pos["f_pos"],
        "laser": state["laser"],
        "intensity": min(float(state["intensity"]), 10),
        "filter": state["filter"],
        "zoom": state["zoom"],
        "shutterconfig": state["shutterconfig"],
        "folder": str(folder),
        "filename": filename,
        "image_writer_plugin": "RAW_Writer",
        "etl_l_offset": state["etl_l_offset"],
        "etl_l_amplitude": state["etl_l_amplitude"],
        "etl_r_offset": state["etl_r_offset"],
        "etl_r_amplitude": state["etl_r_amplitude"],
        "processing": "MAX",
    }


def test_live_demo_busy_gate_acknowledges_and_serializes_mcp_tcp():
    """Prove accepted -> busy rejection -> completion -> accepted on the real demo Core."""
    host, port, token, _hold, request_timeout, _root, _etl, _pid = _live_config()
    if not token:
        pytest.skip("set MESOSPIM_LIVE_MCP_TOKEN for the live MCP server")
    tool = lambda name, arguments=None: _raw_tool(
        host, port, token, request_timeout, name, arguments)
    limits = _must(tool, "get_limits")
    assert (limits.get("stage") or {}).get("stage_type") == "DemoStage"

    tcp_host = os.environ.get("MESOSPIM_LIVE_TCP_HOST", "127.0.0.1")
    tcp_port = os.environ.get("MESOSPIM_LIVE_TCP_PORT")
    tcp_token = os.environ.get("MESOSPIM_LIVE_TCP_TOKEN")
    if tcp_host not in {"127.0.0.1", "localhost"} or not tcp_port or not tcp_token:
        pytest.skip("set loopback MESOSPIM_LIVE_TCP_PORT and MESOSPIM_LIVE_TCP_TOKEN")

    state_keys = [
        "position", "laser", "intensity", "filter", "zoom", "shutterconfig",
        "etl_l_offset", "etl_l_amplitude", "etl_r_offset", "etl_r_amplitude",
    ]
    original = _must(tool, "get_state_all", {"keys": state_keys})
    original_acquisitions = _must(tool, "get_acquisition_list")["acquisitions"]
    original_intensity = original["intensity"]
    alternate = _bounded_delta(original_intensity, 0, 100, 1)
    temp_folder = Path(tempfile.mkdtemp(prefix="mesospim_demo_busy_"))
    acquisition = _demo_acquisition(temp_folder, "busy-gate.raw", original)
    acquisition.update({
        "z_end": float(acquisition["z_start"]) + 2,
        "planes": 3,
    })
    client = RemoteControl(tcp_host, int(tcp_port), tcp_token, timeout=request_timeout)
    try:
        _must(tool, "set_acquisition_list", {
            "acquisitions": [acquisition], "selected_row": 0})
        ok, accepted = tool("run_acquisition_list", {})
        assert ok
        operation = accepted["operation"]
        assert accepted["accepted"] is True
        assert accepted["accepted_command"] == "run_acquisition_list"
        assert operation["status"] == "processing"

        with pytest.raises(RuntimeError) as rejected:
            client.call("set_intensity", intensity=alternate, wait=True)
        message = str(rejected.value)
        assert "system busy" in message
        assert "run_acquisition_list" in message
        assert operation["id"] in message

        progress = client.call("get_progress")
        assert progress["operation"]["id"] == operation["id"]
        assert progress["operation"]["status"] == "processing"

        def completed():
            current = _must(tool, "get_progress")["operation"]
            return current if current.get("status") == "completed" else None

        final_operation = _wait_until(completed, "run_acquisition_list completion")
        assert final_operation["id"] == operation["id"]

        next_call = client.call("set_intensity", intensity=alternate, wait=True)
        assert next_call["accepted"] is True
        assert next_call["accepted_command"] == "set_intensity"
        assert next_call["operation"]["status"] == "completed"
    finally:
        try:
            _must(tool, "set_intensity", {"intensity": original_intensity, "wait": True})
        except Exception:
            pass
        try:
            _must(tool, "set_acquisition_list", {
                "acquisitions": original_acquisitions, "selected_row": 0})
        except Exception:
            pass
        client.close()
        shutil.rmtree(temp_folder, ignore_errors=True)


def test_live_demo_all_54_commands_are_functional_safe_and_restored(request):
    host, port, token, hold, request_timeout, demo_root, etl_path, process_id = _live_config()
    transport = os.environ.get("MESOSPIM_LIVE_DEMO_TRANSPORT", "mcp").lower()
    if transport == "mcp":
        if not token:
            pytest.skip("set MESOSPIM_LIVE_MCP_TOKEN for the live MCP server")
        tool = lambda name, arguments=None: _raw_tool(
            host, port, token, request_timeout, name, arguments)
    elif transport == "tcp":
        tcp_host = os.environ.get("MESOSPIM_LIVE_TCP_HOST", "127.0.0.1")
        tcp_port = os.environ.get("MESOSPIM_LIVE_TCP_PORT")
        tcp_token = os.environ.get("MESOSPIM_LIVE_TCP_TOKEN")
        if tcp_host not in {"127.0.0.1", "localhost"} or not tcp_port or not tcp_token:
            pytest.skip("set loopback MESOSPIM_LIVE_TCP_PORT and MESOSPIM_LIVE_TCP_TOKEN")
        tcp_client = RemoteControl(
            tcp_host, int(tcp_port), tcp_token, timeout=request_timeout)
        request.addfinalizer(tcp_client.close)
        tool = lambda name, arguments=None: _raw_tcp_tool(
            tcp_client, name, arguments)
    else:
        raise ValueError("MESOSPIM_LIVE_DEMO_TRANSPORT must be 'mcp' or 'tcp'")

    limits = _must(tool, "get_limits")
    stage_type = (limits.get("stage") or {}).get("stage_type")
    if stage_type != "DemoStage":
        pytest.fail(f"refusing all-command sweep: remote stage_type is {stage_type!r}, not 'DemoStage'")

    capabilities = _must(tool, "get_capabilities")
    assert set(capabilities["commands"]) == set(VALID_CASES)
    assert len(capabilities["commands"]) == 54

    # Repeated image-series setup/teardown in the same Qt process can destabilize
    # the demo camera/writer threads.  One complete sweep per app process is enough
    # to cover every command and is the safe repeat boundary discovered on the bench.
    sentinel = Path(tempfile.gettempdir()) / f".mesospim_demo_all_{process_id}.done"
    if sentinel.exists():
        pytest.skip(
            f"all-command sweep already ran for mesoSPIM PID {process_id}; "
            "restart the app before repeating it")
    sentinel.write_text("all-command live demo sweep started\n", encoding="utf-8")

    state_keys = [
        "state", "position", "selected_row", "shutterstate", "ETL_cfg_file",
        "filter", "zoom", "laser", "intensity", "shutterconfig",
        "camera_exposure_time", "etl_l_delay_%", "etl_l_ramp_rising_%",
        "etl_l_ramp_falling_%", "etl_l_amplitude", "etl_l_offset",
        "etl_r_delay_%", "etl_r_ramp_rising_%", "etl_r_ramp_falling_%",
        "etl_r_amplitude", "etl_r_offset", "galvo_l_frequency",
        "laser_l_delay_%",
    ]
    original = _must(tool, "get_state_all", {"keys": state_keys})
    original_acquisitions = _must(tool, "get_acquisition_list")["acquisitions"]
    etl_backup = etl_path.read_bytes()
    temp_folder = Path(tempfile.mkdtemp(prefix="mesospim_demo_all_"))
    failures = []
    seen = []
    connection_lost = False

    config = _must(tool, "get_config")
    filters = config["filters"]
    zooms = [item["name"] for item in config["zooms"]]
    lasers = [item["name"] for item in config["lasers"]]
    shutters = config["shutter_configs"]
    axes = limits["enforced"]["axes"]

    alt_filter = _different(filters, original["filter"])
    alt_zoom = _different(zooms, original["zoom"])
    alt_laser = _different(lasers, original["laser"])
    alt_shutter = _different(shutters, original["shutterconfig"])
    alt_intensity = _bounded_delta(original["intensity"], 0, 100, 7)
    x_target = _bounded_delta(original["position"]["x_pos"], *axes["x"], 100)
    relative_delta = -25 if x_target - 25 >= axes["x"][0] else 25
    relative_target = x_target + relative_delta

    acquisition = _demo_acquisition(temp_folder, "set-list.raw", original)
    cases = copy.deepcopy(VALID_CASES)
    cases.update({
        "move_absolute": {"targets": {"x": x_target}},
        "move_relative": {"deltas": {"x": relative_delta}},
        "zero": {"axes": ["x"]},
        "unzero": {"axes": ["x"]},
        "set_state": {"settings": {"intensity": alt_intensity}},
        "set_filter": {"filter": alt_filter, "wait": True},
        "set_zoom": {"zoom": alt_zoom, "wait": True, "update_etl": False},
        "set_laser": {"laser": alt_laser, "wait": True, "update_etl": False},
        "set_intensity": {"intensity": max(0, alt_intensity - 1), "wait": True},
        "set_shutterconfig": {"shutterconfig": alt_shutter},
        "set_camera": {"camera_exposure_time": float(original["camera_exposure_time"]) + 0.001},
        "set_etl": {"etl_l_amplitude": float(original["etl_l_amplitude"]) + 0.01},
        "set_galvo": {"galvo_l_frequency": float(original["galvo_l_frequency"]) + 0.1},
        "set_laser_timing": {"laser_l_delay_%": _bounded_delta(original["laser_l_delay_%"], 0, 100, 1)},
        "reload_etl_config": {"path": str(etl_path), "wait": True},
        "update_etl_from_laser": {"laser": alt_laser, "wait": True},
        "update_etl_from_zoom": {"zoom": alt_zoom, "wait": True},
        "set_mode": {"mode": "live"},
        "set_acquisition_list": {"acquisitions": [acquisition], "selected_row": 0},
        "acquire_start": {"acquisition": _demo_acquisition(temp_folder, "acquire-start.raw", original)},
        "stat_files": {"files": [str(temp_folder / "acquire-start.raw")]},
        "get_disk_space": {"acquisitions": [acquisition]},
        "check_motion_limits": {"acquisitions": [acquisition]},
        "time_lapse_start": {"timepoints": 1, "interval_sec": 0},
    })

    def state_value(key):
        return _must(tool, "get_state_all", {"keys": [key]}).get(key)

    def position():
        return _must(tool, "get_position")

    def stop_and_wait():
        stopping = _must(tool, "stop_activity")
        _wait_for_operation(tool, stopping, "stop_activity")
        _wait_until(lambda: state_value("state") == "idle", "idle state")

    def install_acquisition(filename):
        item = _demo_acquisition(temp_folder, filename, original)
        _must(tool, "set_acquisition_list", {"acquisitions": [item], "selected_row": 0})

    def verify(name, result):
        if name == "move_absolute":
            assert position()["x"] == x_target
        elif name == "move_relative":
            assert position()["x"] == relative_target
        elif name == "zero":
            _wait_until(lambda: position()["x"] == 0, "zeroed X")
        elif name == "unzero":
            _wait_until(lambda: position()["x"] == relative_target, "unzeroed X")
        elif name in {"set_state", "set_intensity"}:
            expected = cases[name].get("settings", {}).get("intensity", cases[name].get("intensity"))
            _wait_until(lambda: state_value("intensity") == expected, f"{name} readback")
        elif name == "set_filter":
            _wait_until(lambda: state_value("filter") == alt_filter, "filter readback")
        elif name == "set_zoom":
            _wait_until(lambda: state_value("zoom") == alt_zoom, "zoom readback")
        elif name == "set_laser":
            _wait_until(lambda: state_value("laser") == alt_laser, "laser readback")
        elif name == "set_shutterconfig":
            _wait_until(lambda: state_value("shutterconfig") == alt_shutter, "shutter config readback")
        elif name in {"set_camera", "set_etl", "set_galvo", "set_laser_timing"}:
            key, expected = next(iter(cases[name].items()))
            _wait_until(lambda: state_value(key) == expected, f"{key} readback")
        elif name == "open_shutters":
            assert result["shutterstate"] is True
        elif name == "close_shutters":
            assert result["shutterstate"] is False
        elif name in {"set_mode", "start_live"}:
            _wait_until(lambda: state_value("state") == "live", f"{name} mode")
        elif name == "start_visual_mode":
            _wait_until(lambda: state_value("state") == "visual_mode", "visual mode")
        elif name == "start_lightsheet_alignment_mode":
            _wait_until(lambda: state_value("state") == "lightsheet_alignment_mode", "alignment mode")
        elif name == "load_sample":
            _wait_until(lambda: position()["y"] == limits["stage"]["y_load_position"], "sample load position")
        elif name == "unload_sample":
            _wait_until(lambda: position()["y"] == limits["stage"]["y_unload_position"], "sample unload position")
        elif name == "center_sample":
            _wait_until(lambda: position()["x"] == limits["stage"]["x_center_position"], "sample center X")
        elif name == "set_acquisition_list":
            assert result["count"] == 1
            assert len(_must(tool, "get_acquisition_list")["acquisitions"]) == 1
        elif name in {"run_acquisition_list", "run_selected_acquisition", "preview_acquisition", "snap"}:
            assert result["scheduled"] is True
        elif name == "acquire_start":
            assert result["started"] is True and result["planes"] == 1
        elif name == "get_disk_space":
            assert result["free_bytes"] >= 0 and result["required_bytes"] >= 0
        elif name == "check_motion_limits":
            assert isinstance(result["outside_limits"], list)
        elif name == "self_test":
            assert result["ok"] is True
        elif name == "time_lapse_start":
            assert result["started"] is True
        elif name == "time_lapse_stop":
            assert result["stopped"] is True
        else:
            assert isinstance(result, dict)

    acquisition_actions = {
        "run_acquisition_list": "run-list.raw",
        "run_selected_acquisition": "run-selected.raw",
        "preview_acquisition": "preview.raw",
    }
    modes_to_stop = {
        "set_mode", "start_live", "start_visual_mode",
        "start_lightsheet_alignment_mode", "snap",
    }

    try:
        for index, name in enumerate(VALID_CASES, 1):
            kind = "CHANGE" if name in OPERATIONAL_COMMANDS else "READ"
            if name == "procedure":
                kind = "SAFE ERROR"
            print(f"[{index:02d}/54] {kind:10s} {name}", flush=True)
            seen.append(name)
            try:
                if name in acquisition_actions:
                    install_acquisition(acquisition_actions[name])
                before_save_mtime = etl_path.stat().st_mtime_ns if name == "save_etl_config" else None
                ok, result = tool(name, cases[name])
                if name == "procedure":
                    assert not ok and "not implemented" in str(result)
                else:
                    assert ok, result
                    verify(name, result)
                if name == "save_etl_config":
                    _wait_until(
                        lambda: etl_path.stat().st_mtime_ns != before_save_mtime,
                        "demo ETL save")
                    etl_path.write_bytes(etl_backup)
                if name in modes_to_stop:
                    time.sleep(hold)
                    stop_and_wait()
                elif name != "procedure":
                    _wait_for_operation(tool, result, name)
                if name in acquisition_actions or name == "acquire_start":
                    _wait_until(lambda: state_value("state") == "idle", f"{name} idle state")
                time.sleep(hold)
            except Exception as exc:  # continue so one run reports every broken command
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
                print(f"           FAIL {failures[-1]}", flush=True)
                if isinstance(exc, OSError):
                    connection_lost = True
                    print("           ABORT remote server connection was lost; app restart required", flush=True)
                    break
                try:
                    stopped = _must(tool, "stop_activity")
                    _wait_for_operation(tool, stopped, "failure cleanup stop_activity")
                except Exception:
                    pass
    finally:
        cleanup_errors = []
        cleanup_calls = (
            ("time_lapse_stop", {}),
            ("stop_activity", {}),
            ("unzero", {"axes": ["x"]}),
            ("move_absolute", {"targets": {
                axis: original["position"][axis + "_pos"]
                for axis in ("x", "y", "z", "f", "theta")
            }}),
            ("set_filter", {"filter": original["filter"], "wait": True}),
            ("set_zoom", {"zoom": original["zoom"], "wait": True, "update_etl": False}),
            ("set_laser", {"laser": original["laser"], "wait": True, "update_etl": False}),
            ("set_intensity", {"intensity": original["intensity"], "wait": True}),
            ("set_shutterconfig", {"shutterconfig": original["shutterconfig"]}),
            ("set_camera", {"camera_exposure_time": original["camera_exposure_time"]}),
            ("set_etl", {key: original[key] for key in (
                "etl_l_delay_%", "etl_l_ramp_rising_%", "etl_l_ramp_falling_%",
                "etl_l_amplitude", "etl_l_offset", "etl_r_delay_%",
                "etl_r_ramp_rising_%", "etl_r_ramp_falling_%",
                "etl_r_amplitude", "etl_r_offset")}),
            ("set_galvo", {"galvo_l_frequency": original["galvo_l_frequency"]}),
            ("set_laser_timing", {"laser_l_delay_%": original["laser_l_delay_%"]}),
            ("set_state", {"settings": {"ETL_cfg_file": original["ETL_cfg_file"]}}),
            ("set_acquisition_list", {
                "acquisitions": original_acquisitions,
                "selected_row": original.get("selected_row") or 0,
            }),
            ("open_shutters" if original.get("shutterstate") else "close_shutters", {}),
        )
        if not connection_lost:
            for name, arguments in cleanup_calls:
                try:
                    cleanup_result = _must(tool, name, arguments)
                    _wait_for_operation(tool, cleanup_result, f"cleanup {name}")
                except Exception as exc:
                    cleanup_errors.append(f"{name}: {exc}")
                    if isinstance(exc, OSError):
                        connection_lost = True
                        break
        try:
            etl_path.write_bytes(etl_backup)
        except Exception as exc:
            cleanup_errors.append(f"restore ETL file: {exc}")
        try:
            shutil.rmtree(temp_folder)
        except Exception as exc:
            cleanup_errors.append(f"remove temp acquisition folder: {exc}")
        if cleanup_errors:
            failures.extend(f"cleanup {item}" for item in cleanup_errors)

    assert seen == list(VALID_CASES)
    if connection_lost:
        pytest.fail(
            "remote server connection was lost; mesoSPIM app restart required:\n"
            + "\n".join(failures))
    final_position = _must(tool, "get_position")
    assert final_position == {
        axis: original["position"][axis + "_pos"]
        for axis in ("x", "y", "z", "f", "theta")
    }
    assert etl_path.read_bytes() == etl_backup
    assert not failures, "all-command demo sweep failures:\n" + "\n".join(failures)
    print("ALL 54 COMMANDS VERIFIED; 40 OPERATIONAL CALLS EXECUTED; DEMO STATE RESTORED", flush=True)

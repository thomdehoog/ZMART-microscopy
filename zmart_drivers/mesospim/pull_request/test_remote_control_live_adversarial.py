"""Opt-in bounded concurrency stress for the real mesoSPIM demo operation gate."""
from __future__ import annotations

import os
import json
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from demo_client import RemoteControl
from test_remote_control_live_demo_all import (
    _bounded_delta,
    _demo_acquisition,
    _live_config,
    _must,
    _raw_tcp_tool,
    _raw_tool,
    _wait_for_operation,
)


pytestmark = pytest.mark.live_adversarial

MUTATION_ATTEMPTS = 16
READ_ATTEMPTS = 8
MAX_WORKERS = 8
REJECTED_REQUEST_TIMEOUT = 2.0


def _selected_lanes():
    transport = os.environ.get("MESOSPIM_LIVE_ADVERSARIAL_TRANSPORT", "both").lower()
    try:
        return {"mcp": ("mcp",), "tcp": ("tcp",), "both": ("mcp", "tcp")}[transport]
    except KeyError as exc:
        raise ValueError(
            "MESOSPIM_LIVE_ADVERSARIAL_TRANSPORT must be 'mcp', 'tcp', or 'both'") from exc


def _rejected_tcp_raw(host, port, token, payload):
    client = RemoteControl(host, int(port), token, timeout=REJECTED_REQUEST_TIMEOUT)
    try:
        client._send(payload)
        reply = client._recv()
        assert "__MESOSPIM_OK__" not in reply, reply
    finally:
        client.close()


def _rejected_mcp_raw(host, port, token, body):
    headers = {"Content-Type": "application/json", "Origin": "http://127.0.0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://{host}:{port}/mcp", data=body.encode("utf-8"), headers=headers,
        method="POST")
    try:
        with urllib.request.urlopen(
                request, timeout=REJECTED_REQUEST_TIMEOUT) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 400


def test_real_demo_rejects_hostile_api_corpus_and_recovers():
    """Try to break selected live APIs, proving refusals leave DemoStage unchanged."""
    host, port, token, _hold, request_timeout, _root, _etl, _pid = _live_config(
        "MESOSPIM_RUN_LIVE_ADVERSARIAL")
    lanes = _selected_lanes()
    if "mcp" in lanes and not token:
        pytest.skip("set MESOSPIM_LIVE_MCP_TOKEN for the live MCP server")
    tcp_host = os.environ.get("MESOSPIM_LIVE_TCP_HOST", "127.0.0.1")
    tcp_port = os.environ.get("MESOSPIM_LIVE_TCP_PORT")
    tcp_token = os.environ.get("MESOSPIM_LIVE_TCP_TOKEN")
    if "tcp" in lanes and (
            tcp_host not in {"127.0.0.1", "localhost"} or not tcp_port or not tcp_token):
        pytest.skip("set loopback MESOSPIM_LIVE_TCP_PORT and MESOSPIM_LIVE_TCP_TOKEN")

    mcp_tool = lambda name, arguments=None: _raw_tool(
        host, port, token, request_timeout, name, arguments)

    def tcp_call(name, arguments):
        client = RemoteControl(
            tcp_host, int(tcp_port), tcp_token, timeout=REJECTED_REQUEST_TIMEOUT)
        try:
            return _raw_tcp_tool(client, name, arguments)
        finally:
            client.close()

    def lane_call(lane, name, arguments=None):
        return mcp_tool(name, arguments) if lane == "mcp" else tcp_call(
            name, arguments or {})

    tool = lambda name, arguments=None: lane_call(lanes[0], name, arguments)
    limits = _must(tool, "get_limits")
    if (limits.get("stage") or {}).get("stage_type") != "DemoStage":
        pytest.fail("refusing live adversarial attacks outside DemoStage")
    state_keys = [
        "state", "position", "intensity", "filter", "zoom", "laser",
        "shutterconfig", "shutterstate", "camera_exposure_time",
        "etl_l_delay_%", "galvo_l_duty_cycle", "laser_l_delay_%",
    ]
    original = _must(tool, "get_state_all", {"keys": state_keys})
    assert original["state"] == "idle"

    attacks = [
        (name, {}) for name in ("__class__", "__globals__", "eval", "os.system")
    ]
    position = original["position"]
    for axis, bounds in limits["enforced"]["axes"].items():
        if bounds:
            attacks.append(("move_absolute", {"targets": {axis: bounds[1] + 1}}))
            attacks.append(("move_relative", {
                "deltas": {axis: bounds[1] - position[axis + "_pos"] + 1}}))
    attacks.extend([
        ("move_absolute", {"targets": {"not_an_axis": 1}}),
        ("move_absolute", {"targets": {}}),
        ("set_intensity", {"intensity": True}),
        ("set_intensity", {"intensity": 101}),
        ("set_filter", {"filter": "__missing_filter__"}),
        ("set_state", {"settings": {"x_max": 999999999}}),
        ("set_state", {"settings": {"state": "__invalid_remote_state__"}}),
        ("set_camera", {"camera_exposure_time": "instant"}),
        ("set_etl", {"etl_l_delay_%": -1}),
        ("set_galvo", {"galvo_l_duty_cycle": 101}),
        ("set_laser_timing", {"laser_l_delay_%": -1}),
        ("set_acquisition_list", {"acquisitions": "not-a-list"}),
        ("acquire_start", {"acquisition": []}),
        ("set_mode", {"mode": "__invalid_mode__"}),
    ])
    assert len(attacks) <= 32

    try:
        for lane in lanes:
            for name, arguments in attacks:
                ok, reply = lane_call(lane, name, arguments)
                assert not ok, f"{lane} accepted hostile {name}: {arguments!r} -> {reply!r}"

        raw_count = 0
        if "tcp" in lanes:
            for payload in (
                '{"ping":{},"get_state":{}}',
                '{"set_intensity":{"intensity":1},"set_intensity":{"intensity":2}}',
                '{"set_intensity":{"intensity":NaN}}',
                '[]',
            ):
                _rejected_tcp_raw(tcp_host, tcp_port, tcp_token, payload)
                raw_count += 1
        if "mcp" in lanes:
            for body in (
                '{',
                '{"jsonrpc":"2.0","id":1,"method":"tools/list","method":"tools/call"}',
                '{"jsonrpc":"2.0","id":NaN,"method":"tools/list"}',
            ):
                _rejected_mcp_raw(host, port, token, body)
                raw_count += 1

        after = _must(tool, "get_state_all", {"keys": state_keys})
        assert after == original
        for lane in lanes:
            ok, hello = lane_call(lane, "hello", {})
            assert ok and hello["app"] == "mesoSPIM-control"
        print(
            "LIVE HOSTILE API CORPUS VERIFIED: "
            f"{len(attacks) * len(lanes) + raw_count} rejected attacks; "
            f"state unchanged; {','.join(lanes)} healthy",
            flush=True,
        )
    finally:
        for name, arguments in (
            ("set_mode", {"mode": "idle"}),
            ("move_absolute", {"targets": {
                axis: original["position"][axis + "_pos"]
                for axis in ("x", "y", "z", "f", "theta")
            }}),
            ("set_filter", {"filter": original["filter"], "wait": True}),
            ("set_zoom", {"zoom": original["zoom"], "wait": True, "update_etl": False}),
            ("set_laser", {"laser": original["laser"], "wait": True, "update_etl": False}),
            ("set_intensity", {"intensity": original["intensity"], "wait": True}),
            ("set_shutterconfig", {"shutterconfig": original["shutterconfig"]}),
        ):
            try:
                cleanup = _must(tool, name, arguments)
                _wait_for_operation(tool, cleanup, f"hostile corpus cleanup {name}")
            except Exception:
                pass


def test_real_demo_busy_gate_survives_bounded_mcp_tcp_concurrency():
    """One real operation must atomically reject a mixed 24-call concurrent burst."""
    host, port, token, _hold, request_timeout, _root, _etl, process_id = _live_config(
        "MESOSPIM_RUN_LIVE_ADVERSARIAL")
    lanes = _selected_lanes()
    if "mcp" in lanes and not token:
        pytest.skip("set MESOSPIM_LIVE_MCP_TOKEN for the live MCP server")

    tcp_host = os.environ.get("MESOSPIM_LIVE_TCP_HOST", "127.0.0.1")
    tcp_port = os.environ.get("MESOSPIM_LIVE_TCP_PORT")
    tcp_token = os.environ.get("MESOSPIM_LIVE_TCP_TOKEN")
    if "tcp" in lanes and (
            tcp_host not in {"127.0.0.1", "localhost"} or not tcp_port or not tcp_token):
        pytest.skip("set loopback MESOSPIM_LIVE_TCP_PORT and MESOSPIM_LIVE_TCP_TOKEN")

    mcp_tool = lambda name, arguments=None: _raw_tool(
        host, port, token, request_timeout, name, arguments)

    def tcp_call(name, arguments):
        client = RemoteControl(
            tcp_host, int(tcp_port), tcp_token, timeout=request_timeout)
        try:
            return _raw_tcp_tool(client, name, arguments)
        finally:
            client.close()

    def lane_call(lane, name, arguments=None):
        return mcp_tool(name, arguments) if lane == "mcp" else tcp_call(
            name, arguments or {})

    tool = lambda name, arguments=None: lane_call(lanes[0], name, arguments)
    limits = _must(tool, "get_limits")
    if (limits.get("stage") or {}).get("stage_type") != "DemoStage":
        pytest.fail("refusing live adversarial stress outside DemoStage")

    sentinel = Path(tempfile.gettempdir()) / f".mesospim_demo_busy_stress_{process_id}.done"
    if sentinel.exists():
        pytest.skip(
            f"live busy stress already ran for mesoSPIM PID {process_id}; restart first")
    sentinel.write_text("bounded live busy stress started\n", encoding="utf-8")

    state_keys = [
        "position", "laser", "intensity", "filter", "zoom", "shutterconfig",
        "etl_l_offset", "etl_l_amplitude", "etl_r_offset", "etl_r_amplitude",
    ]
    original = _must(tool, "get_state_all", {"keys": state_keys})
    original_acquisitions = _must(tool, "get_acquisition_list")["acquisitions"]
    alternate_intensity = _bounded_delta(original["intensity"], 0, 100, 1)
    temp_folder = Path(tempfile.mkdtemp(prefix="mesospim_demo_busy_stress_"))
    acquisition = _demo_acquisition(temp_folder, "busy-stress.raw", original)
    z_start = float(acquisition["z_start"])
    z_limit = limits["enforced"]["axes"]["z"]
    if not z_limit or z_start + 4 > z_limit[1]:
        pytest.fail("demo Z range is too small for the five-plane busy stress acquisition")
    acquisition.update({"z_end": z_start + 4, "planes": 5})
    accepted = None

    try:
        _must(tool, "set_acquisition_list", {
            "acquisitions": [acquisition], "selected_row": 0})
        accepted = _must(tool, "run_acquisition_list")
        operation = accepted["operation"]
        assert operation["status"] == "processing"

        attempts = []
        for index in range(MUTATION_ATTEMPTS):
            attempts.append(("mutation", lanes[index % len(lanes)]))
            if index < READ_ATTEMPTS:
                attempts.append(("read", lanes[(index + 1) % len(lanes)]))
        release = threading.Event()

        def attempt(item):
            release.wait()
            started = time.perf_counter()
            kind, lane = item
            name = "set_intensity" if kind == "mutation" else "get_progress"
            arguments = {"intensity": alternate_intensity, "wait": True} if (
                kind == "mutation") else {}
            ok, reply = lane_call(lane, name, arguments)
            return kind, lane, ok, reply, time.perf_counter() - started

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(attempt, item) for item in attempts]
            burst_started = time.perf_counter()
            release.set()
            results = [future.result() for future in futures]
            burst_elapsed = time.perf_counter() - burst_started

        for kind, _lane, ok, reply, _latency in results:
            if kind == "mutation":
                assert not ok, reply
                error = str(reply.get("error", reply))
                assert "system busy" in error
                assert operation["id"] in error
                assert operation["command"] in error
            else:
                assert ok, reply
                assert reply["operation"]["id"] == operation["id"]
                assert reply["operation"]["status"] == "processing"

        latencies = sorted(result[4] for result in results)
        p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
        print(
            "LIVE BUSY STRESS VERIFIED: "
            f"{MUTATION_ATTEMPTS} mutations rejected, {READ_ATTEMPTS} reads served, "
            f"lanes={','.join(lanes)}, burst={burst_elapsed:.3f}s, "
            f"p95={p95:.3f}s, max={latencies[-1]:.3f}s",
            flush=True,
        )

        unchanged = _must(tool, "get_state_all", {"keys": ["intensity"]})
        assert unchanged["intensity"] == original["intensity"]
        _wait_for_operation(tool, accepted, "busy stress acquisition")

        for lane in lanes:
            ok, reopened = lane_call(lane, "set_intensity", {
                "intensity": alternate_intensity, "wait": True})
            assert ok, reopened
            assert reopened["operation"]["status"] == "completed"
        restored = _must(tool, "set_intensity", {
            "intensity": original["intensity"], "wait": True})
        assert restored["operation"]["status"] == "completed"
    finally:
        if accepted is not None:
            try:
                _wait_for_operation(tool, accepted, "busy stress cleanup")
            except Exception:
                pass
        for name, arguments in (
            ("set_intensity", {"intensity": original["intensity"], "wait": True}),
            ("move_absolute", {"targets": {
                axis: original["position"][axis + "_pos"]
                for axis in ("x", "y", "z", "f", "theta")
            }}),
            ("set_acquisition_list", {
                "acquisitions": original_acquisitions, "selected_row": 0}),
        ):
            try:
                cleanup = _must(tool, name, arguments)
                _wait_for_operation(tool, cleanup, f"busy stress cleanup {name}")
            except Exception:
                pass
        shutil.rmtree(temp_folder, ignore_errors=True)

    final = _must(tool, "get_state_all", {"keys": ["intensity", "position"]})
    assert final["intensity"] == original["intensity"]
    assert final["position"] == original["position"]

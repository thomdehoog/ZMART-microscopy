"""Opt-in valid live MCP and TCP tests that change and restore the device.

This module is never allowed to move a device unless both explicit safety gates
are set. It is separate from normal CI and from the adversarial corpus.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse

import pytest

from demo_client import RemoteControl, mcp_call


pytestmark = pytest.mark.live_valid


def _safety_config():
    if os.environ.get("MESOSPIM_ALLOW_DEVICE_CHANGE") != "1":
        pytest.skip("set MESOSPIM_ALLOW_DEVICE_CHANGE=1 to permit a live device move")
    if os.environ.get("MESOSPIM_OPERATOR_PRESENT") != "1":
        pytest.skip("set MESOSPIM_OPERATOR_PRESENT=1 when an operator is at the instrument")

    delta = float(os.environ.get("MESOSPIM_TEST_X_DELTA_UM", "100"))
    if not 0 < abs(delta) <= 1000:
        raise ValueError("MESOSPIM_TEST_X_DELTA_UM must be >0 and <=1000 um")
    hold = float(os.environ.get("MESOSPIM_TEST_HOLD_SECONDS", "0"))
    if not 0 <= hold <= 2:
        raise ValueError("MESOSPIM_TEST_HOLD_SECONDS must be between 0 and 2 seconds")
    return delta, hold


def _mcp_config():
    delta, hold = _safety_config()
    url = os.environ.get("MESOSPIM_LIVE_MCP_URL", "http://127.0.0.1:42100/mcp")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("live-valid tests require a loopback http:// MCP URL")
    if parsed.path != "/mcp" or parsed.port is None:
        raise ValueError("MESOSPIM_LIVE_MCP_URL must include a port and /mcp path")
    token = os.environ.get("MESOSPIM_LIVE_MCP_TOKEN")
    if not token:
        pytest.skip("set MESOSPIM_LIVE_MCP_TOKEN for the live MCP server")
    return parsed.hostname, parsed.port, token, delta, hold


def _tcp_config():
    delta, hold = _safety_config()
    host = os.environ.get("MESOSPIM_LIVE_TCP_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("live-valid tests require a loopback TCP host")
    port = int(os.environ.get("MESOSPIM_LIVE_TCP_PORT", "42000"))
    token = os.environ.get("MESOSPIM_LIVE_TCP_TOKEN")
    if not token:
        pytest.skip("set MESOSPIM_LIVE_TCP_TOKEN for the live TCP server")
    return host, port, token, delta, hold


def _mcp_tool(host, port, token, name, arguments=None):
    reply = mcp_call(host, port, token, "tools/call", name, arguments or {})
    result = reply["result"]
    if result.get("isError"):
        raise RuntimeError(result["content"][0]["text"])
    return json.loads(result["content"][0]["text"])


def _exercise_x_change(tool, transport, requested_delta, hold):
    """Run the same valid move/readback/restore contract through one transport."""
    before = tool("get_position")
    x_limits = tool("get_limits")["enforced"]["axes"]["x"]
    if not x_limits:
        pytest.fail("live config has no enforced X range")

    delta = requested_delta
    target = before["x"] + delta
    if not x_limits[0] <= target <= x_limits[1]:
        delta = -requested_delta
        target = before["x"] + delta
    if not x_limits[0] <= target <= x_limits[1]:
        pytest.fail(f"no safe {abs(requested_delta)} um X move from {before['x']} in {x_limits}")

    changed = None
    try:
        tool("move_absolute", {"targets": {"x": target}})
        changed = tool("get_position")
        assert changed["x"] == target
        if hold:
            time.sleep(hold)

        tool("move_relative", {"deltas": {"x": -delta}})
        restored = tool("get_position")
        assert restored["x"] == before["x"]
    finally:
        current = tool("get_position")
        if current["x"] != before["x"]:
            tool("move_absolute", {"targets": {"x": before["x"]}})

    print(
        f"live {transport} X changed {before['x']} -> {changed['x']} -> {before['x']} "
        f"within {x_limits}"
    )


def test_live_mcp_x_move_changes_position_and_restores_it():
    """Run the valid movement contract through MCP."""
    host, port, token, delta, hold = _mcp_config()
    _exercise_x_change(
        lambda name, arguments=None: _mcp_tool(host, port, token, name, arguments),
        "MCP", delta, hold,
    )


def test_live_tcp_x_move_changes_position_and_restores_it():
    """Run the identical valid movement contract through framed TCP."""
    host, port, token, delta, hold = _tcp_config()
    client = RemoteControl(host, port, token, timeout=10.0)
    try:
        _exercise_x_change(
            lambda name, arguments=None: client.call(name, **(arguments or {})),
            "TCP", delta, hold,
        )
    finally:
        client.close()

"""
Offline tests for the FV4000 RDK spike.
=======================================
Two layers, both fully offline (no Evident software, license, or microscope):
  1. Pure protocol encode/parse.
  2. A real ``RdkClient`` round-trip against the ``MockRdkServer`` (a real TCP
     socket on an ephemeral localhost port) — connect/login, move + read-back,
     error handling.

This validates the transport + framing + client plumbing. It does NOT validate
the real FV4000's behaviour (the device verbs are placeholders).

Run:  pytest -q zmart_drivers/evident/spike/test_rdk_roundtrip.py
"""

from __future__ import annotations

import pytest
from mock_rdk_server import MockRdkServer
from rdk_client import RdkClient, RdkError
from rdk_protocol import encode, parse

# -- pure protocol ------------------------------------------------------------


def test_encode_command():
    assert encode("MVSTG", -50000, 50000) == "MVSTG= -50000,50000"
    assert encode("CONNECT", 0) == "CONNECT= 0"


def test_parse_ack():
    m = parse("MVSTG= +")
    assert m.verb == "MVSTG" and m.ok and not m.is_error and m.args == []


def test_parse_nak():
    m = parse("CHOB= -")
    assert m.is_error and not m.ok


def test_parse_values():
    m = parse("RDSTG= 100.5,200.0")
    assert not m.ok and m.args == ["100.5", "200.0"]


def test_parse_tolerates_crlf():
    m = parse("RDOB= 3\r\n")
    assert m.verb == "RDOB" and m.args == ["3"]


# -- client <-> mock server round-trip ---------------------------------------


@pytest.fixture
def server():
    with MockRdkServer() as s:
        yield s


def test_connect_and_login(server):
    with RdkClient(server.host, server.port):
        assert server.state["logged_in"] is True


def test_stage_round_trip(server):
    with RdkClient(server.host, server.port) as c:
        c.move_stage(-50000, 50000)  # µm
        assert c.read_stage() == (-50000.0, 50000.0)
        assert server.state["x_um"] == -50000.0


def test_focus_round_trip(server):
    with RdkClient(server.host, server.port) as c:
        c.move_z(123.5)
        assert c.read_z() == 123.5


def test_objective_round_trip(server):
    with RdkClient(server.host, server.port) as c:
        c.set_objective(3)
        assert c.read_objective() == 3


def test_unknown_verb_naks(server):
    with RdkClient(server.host, server.port) as c:
        assert c.command("FROBNICATE", 1).is_error


def test_error_reply_raises():
    with MockRdkServer(errors={"MVSTG"}) as s:
        with RdkClient(s.host, s.port) as c:
            with pytest.raises(RdkError):
                c.move_stage(1, 2)


def test_login_gate():
    with MockRdkServer(require_login=True) as s:
        c = RdkClient(s.host, s.port)
        c.connect(login=None)  # connect but do NOT log in
        try:
            assert c.command("RDOB", 0).is_error  # device command gated
        finally:
            c.close()

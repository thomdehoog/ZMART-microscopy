"""MesospimClient <-> MockMesospimServer round-trip over a real localhost socket.

The mock is a faithful Remote Scripting double: it ``exec``s the injected scripts
against a Core-shaped fake and returns the captured console, so these exercise the
real framing + harness + vocabulary, only without a live hardware Core.
"""

from __future__ import annotations

import pytest
from mesospim.connection.client import MesospimClient, MesospimError
from mock_mesospim_server import MockMesospimServer


def test_connect_handshake_populates_server_info(client):
    assert client.server_info.get("app") == "mesoSPIM-control"
    assert client.server_info.get("protocol") == 1


def test_ping_request(client):
    assert client.request("ping").ok


def test_read_timeout_override_is_restored(client):
    # A per-call read_timeout (used for long acquisitions) must apply only to
    # that call and then restore the base socket deadline -- and must never be
    # forwarded as a command argument.
    base = client._sock.gettimeout()
    assert client.request("ping", read_timeout=42.0).ok
    assert client._sock.gettimeout() == base


def test_request_returns_data(client):
    reply = client.request("get_config")
    assert reply.ok
    assert "lasers" in reply.data


def test_try_request_returns_nak_without_raising(client):
    # A command whose injected script fails comes back as a clean NAK, not a
    # client-side crash: the server NAKs named procedures (TODO §5).
    reply = client.try_request("procedure", name="autofocus")
    assert not reply.ok and reply.error


def test_request_raises_on_nak(client):
    with pytest.raises(MesospimError):
        client.request("procedure", name="autofocus")


def test_unknown_command_is_rejected_by_the_server_allowlist(client):
    # An unknown call is not in the server's fixed allowlist, so it never runs;
    # the server replies with an error and the client surfaces it as a failed Reply.
    reply = client.try_request("bogus_command")
    assert not reply.ok and "bogus_command" in reply.error


def test_injected_error(server):
    with MockMesospimServer(port=0, errors={"get_state"}) as s:
        with MesospimClient(s.host, s.port, timeout=3.0) as c:
            with pytest.raises(MesospimError):
                c.request("get_state")


def test_context_manager_connects_and_closes(server):
    with MesospimClient(server.host, server.port, timeout=3.0) as c:
        assert c.connected
    assert not c.connected


def test_request_before_connect_raises(server):
    c = MesospimClient(server.host, server.port, timeout=3.0)
    with pytest.raises(ConnectionError):
        c.try_request("ping")


def test_connect_to_dead_port_raises():
    # Bind then close to obtain a definitely-free port.
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(ConnectionError):
        MesospimClient("127.0.0.1", port, timeout=0.5).connect()


def test_close_is_idempotent(client):
    client.close()
    client.close()  # must not raise

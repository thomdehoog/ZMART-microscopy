"""MesospimClient <-> MockMesospimServer round-trip over a real localhost socket."""

from __future__ import annotations

import pytest
from mesospim.connection.client import MesospimClient, MesospimError
from mock_mesospim_server import MockMesospimServer


def test_connect_handshake_populates_server_info(client):
    assert client.server_info.get("app") == "mesoSPIM-control"
    assert client.server_info.get("protocol") == 1


def test_ping_request(client):
    assert client.request("ping").ok


def test_request_echoes_id_and_returns_data(client):
    reply = client.request("get_config")
    assert reply.ok
    assert "lasers" in reply.data


def test_try_request_returns_nak_without_raising(client):
    reply = client.try_request("bogus_command")
    assert not reply.ok and reply.error


def test_request_raises_on_nak(client):
    with pytest.raises(MesospimError):
        client.request("bogus_command")


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
